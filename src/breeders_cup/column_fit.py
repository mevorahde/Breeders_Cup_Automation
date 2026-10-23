"""Measure displayed text so Excel columns can shrink as well as expand."""
from functools import lru_cache
import sys
import json
import os
from pathlib import Path
import subprocess
import tempfile
import warnings


def excel_autofit(book):
    """Read native Excel AutoFit widths from a private, read-only workbook copy.

    Excel never saves the copy or opens the user's workbook. Only the measured
    widths are applied, preserving workbook values, formulas and manual picks.
    """
    if sys.platform != 'win32':
        return False
    script = r'''
$ErrorActionPreference = 'Stop'
$excel = $null
$workbook = $null
try {
    if ($null -eq [Type]::GetTypeFromProgID('Excel.Application')) {
        Write-Output '{"available":false}'
        exit 0
    }
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    $workbook = $excel.Workbooks.Open($env:BC_AUTOFIT_INPUT, 0, $true)
    $excel.Calculation = -4135
    $widths = @{}
    foreach ($sheet in $workbook.Worksheets) {
        $range = $sheet.Range('A:O')
        $range.WrapText = $false
        $range.Columns.AutoFit() | Out-Null
        $values = @()
        for ($column = 1; $column -le 15; $column++) {
            $values += [double]$sheet.Columns.Item($column).ColumnWidth
        }
        $widths[$sheet.Name] = $values
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($range)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($sheet)
    }
    @{available=$true; widths=$widths} | ConvertTo-Json -Depth 4 -Compress
} finally {
    if ($null -ne $workbook) {
        $workbook.Close($false)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($workbook)
    }
    if ($null -ne $excel) {
        $excel.Quit()
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
    }
}
'''
    with tempfile.TemporaryDirectory(prefix='breeders-autofit-') as directory:
        source=Path(directory)/'measure.xlsx'
        book.save(source)
        environment=os.environ.copy()
        environment['BC_AUTOFIT_INPUT']=str(source)
        script_path=Path(directory)/'autofit.ps1'
        script_path.write_text(script,encoding='utf-8-sig')
        try:
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive',
                                   '-ExecutionPolicy','Bypass','-File',str(script_path)],env=environment,
                                  capture_output=True,text=True,timeout=60,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError(result.stderr.strip())
            measurements=json.loads(result.stdout)
            if not measurements['available']:
                return False
            widths=measurements['widths']
            for sheet in book:
                values=widths[sheet.title]
                if len(values)!=15 or any(not 0<float(v)<=255 for v in values):
                    raise ValueError('Invalid Excel AutoFit widths')
            for sheet in book:
                for col,width in enumerate(widths[sheet.title],1):
                    sheet.column_dimensions[sheet.cell(1,col).column_letter].width=float(width)
            return True
        except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
            warnings.warn(f'Excel AutoFit unavailable; using measured widths: {error}',RuntimeWarning)
            return False


@lru_cache(maxsize=16384)
def text_pixels(text,name,points,bold,italic):
    if sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        gdi.CreateCompatibleDC.argtypes=[wintypes.HDC]
        gdi.CreateCompatibleDC.restype=wintypes.HDC
        gdi.CreateFontW.argtypes=[ctypes.c_int]*13+[wintypes.LPCWSTR]
        gdi.CreateFontW.restype=wintypes.HANDLE
        gdi.SelectObject.argtypes=[wintypes.HDC,wintypes.HANDLE]
        gdi.SelectObject.restype=wintypes.HANDLE
        gdi.DeleteObject.argtypes=[wintypes.HANDLE]
        gdi.DeleteDC.argtypes=[wintypes.HDC]
        class Size(ctypes.Structure):
            _fields_=[('cx',wintypes.LONG),('cy',wintypes.LONG)]
        gdi.GetTextExtentPoint32W.argtypes=[wintypes.HDC,wintypes.LPCWSTR,ctypes.c_int,ctypes.POINTER(Size)]
        dc=gdi.CreateCompatibleDC(None)
        font=gdi.CreateFontW(-round(points*96/72),0,0,0,700 if bold else 400,int(italic),0,0,1,0,0,5,0,name)
        if dc and font:
            original=gdi.SelectObject(dc,font)
            size=Size()
            try:
                if gdi.GetTextExtentPoint32W(dc,text,len(text.encode('utf-16-le'))//2,ctypes.byref(size)):
                    return size.cx
            finally:
                gdi.SelectObject(dc,original)
                gdi.DeleteObject(font)
                gdi.DeleteDC(dc)
        else:
            if font:gdi.DeleteObject(font)
            if dc:gdi.DeleteDC(dc)
    # Portable approximation when Windows font measurement is unavailable.
    return sum(3 if c in " ilI.,:;'|" else 10 if c in 'MW@' else 6 for c in text)*points/11


def fitted_width(cells):
    maximum=0
    for cell in cells:
        if cell.data_type=='f' or cell.value is None:
            continue
        value=cell.value
        text=value.strftime('%m/%d/%Y') if hasattr(value,'strftime') else str(value)
        font=cell.font
        for line in text.splitlines():
            maximum=max(maximum,text_pixels(line,font.name or 'Calibri',float(font.sz or 11),bool(font.b),bool(font.i)))
    digit=text_pixels('0','Calibri',11,False,False) or 7
    return min(255,max(2,(maximum+1)/digit))
