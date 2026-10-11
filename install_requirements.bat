@echo off
echo Installing Auto Deal Searcher dependencies...
echo.

pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Installing Playwright browsers...
playwright install

echo.
echo Setup complete!
echo To run the application, use: python -m src.cli
echo.
pause