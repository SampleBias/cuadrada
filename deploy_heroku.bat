@echo off
SETLOCAL

REM Check if Heroku CLI is installed
where heroku > nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Heroku CLI not found. Please install it first.
    exit /b 1
)

REM Check if user is logged in to Heroku
heroku whoami > nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo You are not logged in to Heroku. Please run 'heroku login' first.
    exit /b 1
)

REM Ask for the app name
set /p APP_NAME=Enter your Heroku app name (or leave blank to create a new app): 

IF "%APP_NAME%"=="" (
    REM Create a new app
    echo Creating a new Heroku app...
    FOR /F "tokens=2 delims=/ " %%i IN ('heroku create') DO set APP_NAME=%%i
    echo Created app: %APP_NAME%
) ELSE (
    REM Check if app exists
    heroku apps:info --app %APP_NAME% > nul 2>&1
    IF %ERRORLEVEL% NEQ 0 (
        echo App does not exist. Creating app '%APP_NAME%'...
        heroku create %APP_NAME%
    ) ELSE (
        echo Using existing app: %APP_NAME%
    )
)

REM Set environment variables
echo Setting up environment variables...
echo Please provide the following environment variables:

set /p CLAUDE_API_KEY=CLAUDE_API_KEY: 
set /p AUTH0_DOMAIN=AUTH0_DOMAIN: 
set /p AUTH0_CLIENT_ID=AUTH0_CLIENT_ID: 
set /p AUTH0_CLIENT_SECRET=AUTH0_CLIENT_SECRET: 
set /p MONGODB_URI=MONGODB_URI: 
set /p STRIPE_SECRET_KEY=STRIPE_SECRET_KEY: 
set /p STRIPE_WEBHOOK_SECRET=STRIPE_WEBHOOK_SECRET: 

REM Set environment variables in Heroku
heroku config:set CLAUDE_API_KEY="%CLAUDE_API_KEY%" --app %APP_NAME%
heroku config:set AUTH0_DOMAIN="%AUTH0_DOMAIN%" --app %APP_NAME%
heroku config:set AUTH0_CLIENT_ID="%AUTH0_CLIENT_ID%" --app %APP_NAME%
heroku config:set AUTH0_CLIENT_SECRET="%AUTH0_CLIENT_SECRET%" --app %APP_NAME%
heroku config:set AUTH0_CALLBACK_URL="https://%APP_NAME%.herokuapp.com/callback" --app %APP_NAME%
heroku config:set AUTH0_BASE_URL="https://%APP_NAME%.herokuapp.com" --app %APP_NAME%
heroku config:set MONGODB_URI="%MONGODB_URI%" --app %APP_NAME%
heroku config:set STRIPE_SECRET_KEY="%STRIPE_SECRET_KEY%" --app %APP_NAME%
heroku config:set STRIPE_WEBHOOK_SECRET="%STRIPE_WEBHOOK_SECRET%" --app %APP_NAME%

REM Deploy to Heroku
echo Deploying to Heroku...
git add .
git commit -m "Prepare for Heroku deployment" || VER>NUL
git push heroku main

echo Deployment complete! Your app is available at: https://%APP_NAME%.herokuapp.com
echo.
echo Important: Make sure to update your Auth0 application settings:
echo - Allowed Callback URLs: https://%APP_NAME%.herokuapp.com/callback
echo - Allowed Logout URLs: https://%APP_NAME%.herokuapp.com/thank-you
echo - Allowed Web Origins: https://%APP_NAME%.herokuapp.com

ENDLOCAL 