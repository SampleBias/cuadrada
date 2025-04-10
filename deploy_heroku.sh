#!/bin/bash

# Check if Heroku CLI is installed
if ! command -v heroku &> /dev/null; then
    echo "Heroku CLI not found. Please install it first."
    exit 1
fi

# Check if user is logged in to Heroku
heroku whoami &> /dev/null
if [ $? -ne 0 ]; then
    echo "You are not logged in to Heroku. Please run 'heroku login' first."
    exit 1
fi

# Ask for the app name
read -p "Enter your Heroku app name (or leave blank to create a new app): " APP_NAME

if [ -z "$APP_NAME" ]; then
    # Create a new app
    echo "Creating a new Heroku app..."
    APP_NAME=$(heroku create | grep -o 'https://[^ ]*\.herokuapp\.com' | sed 's/https:\/\///' | sed 's/\.herokuapp\.com//')
    echo "Created app: $APP_NAME"
else
    # Check if app exists
    heroku apps:info --app $APP_NAME &> /dev/null
    if [ $? -ne 0 ]; then
        echo "App does not exist. Creating app '$APP_NAME'..."
        heroku create $APP_NAME
    else
        echo "Using existing app: $APP_NAME"
    fi
fi

# Set environment variables
echo "Setting up environment variables..."
echo "Please provide the following environment variables:"

read -p "CLAUDE_API_KEY: " CLAUDE_API_KEY
read -p "AUTH0_DOMAIN: " AUTH0_DOMAIN
read -p "AUTH0_CLIENT_ID: " AUTH0_CLIENT_ID
read -p "AUTH0_CLIENT_SECRET: " AUTH0_CLIENT_SECRET
read -p "MONGODB_URI: " MONGODB_URI
read -p "STRIPE_SECRET_KEY: " STRIPE_SECRET_KEY
read -p "STRIPE_WEBHOOK_SECRET: " STRIPE_WEBHOOK_SECRET

# Set environment variables in Heroku
heroku config:set CLAUDE_API_KEY="$CLAUDE_API_KEY" --app $APP_NAME
heroku config:set AUTH0_DOMAIN="$AUTH0_DOMAIN" --app $APP_NAME
heroku config:set AUTH0_CLIENT_ID="$AUTH0_CLIENT_ID" --app $APP_NAME
heroku config:set AUTH0_CLIENT_SECRET="$AUTH0_CLIENT_SECRET" --app $APP_NAME
heroku config:set AUTH0_CALLBACK_URL="https://$APP_NAME.herokuapp.com/callback" --app $APP_NAME
heroku config:set AUTH0_BASE_URL="https://$APP_NAME.herokuapp.com" --app $APP_NAME
heroku config:set MONGODB_URI="$MONGODB_URI" --app $APP_NAME
heroku config:set STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY" --app $APP_NAME
heroku config:set STRIPE_WEBHOOK_SECRET="$STRIPE_WEBHOOK_SECRET" --app $APP_NAME

# Deploy to Heroku
echo "Deploying to Heroku..."
git add .
git commit -m "Prepare for Heroku deployment" || true
git push heroku main

echo "Deployment complete! Your app is available at: https://$APP_NAME.herokuapp.com"
echo ""
echo "Important: Make sure to update your Auth0 application settings:"
echo "- Allowed Callback URLs: https://$APP_NAME.herokuapp.com/callback"
echo "- Allowed Logout URLs: https://$APP_NAME.herokuapp.com/thank-you"
echo "- Allowed Web Origins: https://$APP_NAME.herokuapp.com" 