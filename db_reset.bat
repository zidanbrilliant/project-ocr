@echo off
echo ========================================
echo  VISION AI — Database Reset
echo ========================================
echo.
echo This will DELETE all data and recreate tables.
echo.
set /p confirm="Type 'reset' to continue: "
if /i "%confirm%"=="reset" (
    python scripts/db_reset.py
    echo.
    echo Done. Open http://localhost:8080 to view tables.
) else (
    echo Cancelled.
)
pause
