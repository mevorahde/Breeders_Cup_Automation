"""Measure displayed text so Excel columns can shrink as well as expand."""
from functools import lru_cache
import sys


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
