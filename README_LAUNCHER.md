# TopShelf Launcher

Your TopShelf app launcher is installed and ready to use!

## How to Start

1. **Double-click the `TopShelf` icon on your desktop**
   - The web server will start automatically
   - Your browser will open to the dashboard at http://127.0.0.1:8000/TopShelf.html
   - The Telegram bot will start in the background

2. **The app is running when:**
   - Your browser opens automatically
   - The dashboard loads and shows deals
   - You can send commands to the Telegram bot

## Checking Status

- **Web Dashboard:** http://127.0.0.1:8000/TopShelf.html
- **Logs:** Open the `logs/` folder in the project directory to see detailed activity
  - `web.log` - FastAPI web server output
  - `bot.log` - Telegram bot activity
  - `tray.log` - Launcher application output

## Stopping the App

- **Close the browser window** - The app will keep running in the background
- **Telegram still works** - Send commands from Telegram even if the browser is closed
- **To fully stop:** Open a PowerShell terminal in the project and run:
  ```powershell
  Get-Process -Name python | Where-Object { $_.CommandLine -like '*TopShelf*' -or $_.CommandLine -like '*uvicorn*' } | Stop-Process -Force
  ```

## If Something Goes Wrong

1. Check `logs/tray.log` for startup errors
2. Check `logs/web.log` for dashboard errors  
3. Check `logs/bot.log` for Telegram bot errors
4. Make sure ports 8000 and 49217 aren't in use by other applications
5. Re-run the installer PowerShell script to fix permissions or dependencies

## Telegram Commands

Once the bot is running, you can use:
- `/deals` - See all deals
- `/flower` - Filter by flower products
- `/refresh` - Manually refresh the feed (5-minute cooldown)
- `/help` - Show all available commands
- `/filters` - Manage your saved searches

Enjoy your deals! 🎉
