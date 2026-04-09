# BookMySeat

A Django-based movie booking application with movie listings, theater schedules, seat selection, Razorpay payments, and an admin analytics dashboard.

## Features

- Movie browsing with search, genre filters, language filters, and pagination
- Theater and seat selection
- Razorpay payment flow
- Booking confirmation emails
- Admin dashboard with movie inventory and booking analytics
- Poster image support through Django media files

## Tech Stack

- Python 3.14
- Django 5.1
- PostgreSQL for production
- SQLite for local development
- Razorpay for payments
- WhiteNoise for static files

## Local Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root and set the needed values:

```env
DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///db.sqlite3
EMAIL_HOST_USER=your-email@example.com
EMAIL_HOST_PASSWORD=your-email-password
RAZORPAY_KEY_ID=your-razorpay-key-id
RAZORPAY_KEY_SECRET=your-razorpay-key-secret
RAZORPAY_WEBHOOK_SECRET=your-razorpay-webhook-secret
```

4. Run migrations:

```bash
python manage.py migrate
```

5. Seed demo data:

```bash
python manage.py seed_demo_data
```

6. Start the server:

```bash
python manage.py runserver
```

## Database And Media

- Movie data, theaters, seats, and bookings are stored in the database.
- Poster images are stored in `media/movies/`.
- In production, media files must be present on the deployed server or persistent storage.

## Deployment Notes

This project is configured to work with Render.

### Build Command

Use this if you want migrations and demo data loaded during deploy:

```bash
pip install -r requirements.txt && python manage.py migrate && python manage.py seed_demo_data
```

### Start Command

```bash
gunicorn bookmyseat.wsgi:application --bind 0.0.0.0:$PORT
```

### Environment Variables

Set these in Render:

- `DEBUG=False`
- `SECRET_KEY`
- `DATABASE_URL`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`

## Loading Movie Images

The deployed site can show movie posters if the image files are included and media URLs are served. The app is configured to serve media URLs from Django so poster images can render on the deployed site.

## Useful Commands

```bash
python manage.py check
python manage.py test
python manage.py seed_demo_data
```

## Notes

- If you change the movie catalog, rerun `seed_demo_data` to refresh demo content.
- If you add new poster files, make sure they are available in deployment.
