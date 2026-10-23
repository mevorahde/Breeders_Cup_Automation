# Local reference workbook

The program reads `2024 Breeders Cup Final.xlsx` from this directory to reproduce
the reference formatting and results summary. Copy your original workbook here
after cloning the repository. Keep its `2024` worksheet and layout intact.

Excel workbooks are intentionally excluded from Git. This README is tracked so
the directory and installation instructions exist in a fresh clone.

To use a different local path, run:

```powershell
.\.venv\Scripts\python.exe -m breeders_cup.cli update --template "reference/2024 Breeders Cup Final.xlsx"
```

The automated workbook tests also require this local reference file. The program
never modifies it.
