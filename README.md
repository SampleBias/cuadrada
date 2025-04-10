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
2. Ensure Supabase project is set up with the required tables (see Supabase Setup section)
3. Run the application:
   ```
   python app.py
   ```

## Supabase Setup

1. Create a Supabase account at [supabase.com](https://supabase.com)
2. Create a new project
3. Go to the SQL Editor and create the following tables:

```sql
-- Create users table
CREATE TABLE public.users (
    id SERIAL PRIMARY KEY,
    user_id TEXT UNIQUE NOT NULL,
    email TEXT,
    name TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create subscriptions table
CREATE TABLE public.subscriptions (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES public.users(user_id),
    plan_type TEXT DEFAULT 'free',
    status TEXT DEFAULT 'active',
    max_reviews INTEGER DEFAULT 5,
    current_period_start TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    current_period_end TIMESTAMP WITH TIME ZONE DEFAULT NOW() + INTERVAL '30 days'
);

-- Create reviews table
CREATE TABLE public.reviews (
    id SERIAL PRIMARY KEY,
    user_id TEXT REFERENCES public.users(user_id),
    submission_id TEXT NOT NULL,
    paper_title TEXT,
    decision TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    file_url TEXT
);
```

4. Create storage buckets:
   - Go to Storage in the Supabase dashboard
   - Create two new buckets: `uploads` and `results`
   - Set the privacy settings to allow public access for ease of use
   - For production, set up appropriate RLS policies

5. Add Supabase credentials to your `.env` file:
```
SUPABASE_URL=your_project_url
SUPABASE_KEY=your_anon_key
```

## Heroku Deployment

### Prerequisites
- Heroku CLI installed
- Git installed
- Heroku account
- Supabase account (for database and storage)
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
   heroku config:set SUPABASE_URL=your_supabase_project_url
   heroku config:set SUPABASE_KEY=your_supabase_anon_key
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

2. File storage:
   - The application uses Supabase Storage for storing uploads and results
   - This provides persistent file storage across application restarts
   - The app maintains local temporary copies in `/tmp` when running on Heroku

3. Supabase Database and Storage:
   - Ensure your Supabase URL and API key are properly configured in the environment variables
   - Make sure you've created the required tables and storage buckets
   - For production, set up appropriate Row Level Security (RLS) policies 