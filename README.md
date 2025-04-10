# Cuadrada

Cuadrada is an AI-powered peer review system that helps researchers validate their work with instant feedback.

## Virtual Environment Setup

### On Unix/MacOS
```bash
# Run the setup script
./setup_venv.sh

# Or manually set up:
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### On Windows
```bash
# Run the setup script
setup_venv.bat

# Or manually set up:
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Local Development

1. Set up your environment variables in a `.env` file based on `.env.example`
2. Ensure MongoDB is running locally or you have a MongoDB Atlas connection string
3. Run the application:
   ```
   python app.py
   ```

## Heroku Deployment

### Prerequisites
- Heroku CLI installed
- Git installed
- Heroku account
- MongoDB Atlas account (for database)
- Auth0 account (for authentication)

### Steps to Deploy

1. Log in to Heroku:
   ```
   heroku login
   ```

2. Create a new Heroku app:
   ```
   heroku create your-app-name
   ```

3. Set up the environment variables in Heroku:
   ```
   heroku config:set CLAUDE_API_KEY=your_claude_api_key
   heroku config:set AUTH0_DOMAIN=your_auth0_domain
   heroku config:set AUTH0_CLIENT_ID=your_auth0_client_id
   heroku config:set AUTH0_CLIENT_SECRET=your_auth0_client_secret
   heroku config:set AUTH0_CALLBACK_URL=https://your-app-name.herokuapp.com/callback
   heroku config:set AUTH0_AUDIENCE=https://your_auth0_domain/api/v2/
   heroku config:set AUTH0_BASE_URL=https://your-app-name.herokuapp.com
   heroku config:set MONGODB_URI=your_mongodb_connection_string
   heroku config:set STRIPE_SECRET_KEY=your_stripe_secret_key
   heroku config:set STRIPE_WEBHOOK_SECRET=your_stripe_webhook_secret
   ```

4. Deploy the application to Heroku:
   ```
   git add .
   git commit -m "Prepare for Heroku deployment"
   git push heroku main
   ```

5. Open the application:
   ```
   heroku open
   ```

## Important Notes for Deployment

1. Update Auth0 application settings:
   - Allowed Callback URLs: `https://your-app-name.herokuapp.com/callback`
   - Allowed Logout URLs: `https://your-app-name.herokuapp.com/thank-you`
   - Allowed Web Origins: `https://your-app-name.herokuapp.com`

2. File storage on Heroku:
   - Heroku uses an ephemeral filesystem where files are not permanently stored
   - This application stores files in `/tmp` when running on Heroku
   - For production, consider using Amazon S3 or similar cloud storage service

3. MongoDB Connection:
   - Ensure your MongoDB Atlas connection string is properly configured in the Heroku environment variables
   - The application is designed to retry MongoDB connections if they fail initially 