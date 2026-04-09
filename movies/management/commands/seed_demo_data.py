from io import BytesIO
from datetime import timedelta

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image

from movies.models import Genre, Language, Movie, Seat, Theater


class Command(BaseCommand):
    help = 'Seed demo genres, languages, movies, theaters, and seats.'

    def handle(self, *args, **options):
        genres = [
            'Action',
            'Drama',
            'Comedy',
            'Horror',
            'Romance',
            'Sci-Fi',
            'Thriller',
            'Animation',
        ]
        languages = [
            'English',
            'Hindi',
            'Tamil',
            'Telugu',
            'Kannada',
            'Marathi',
        ]

        for name in genres:
            Genre.objects.get_or_create(name=name)

        for name in languages:
            Language.objects.get_or_create(name=name)

        demo_movies = [
            {
                'name': 'Skyline Legends',
                'rating': 4.6,
                'cast': 'Actor One, Actor Two',
                'description': 'An action-packed adventure across the skyline.',
                'genres': ['Action'],
                'languages': ['English'],
                'poster_color': (220, 53, 69),
                'theater_name': 'IMAX Screen 1',
                'trailer_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            },
            {
                'name': 'Heartbeats',
                'rating': 4.3,
                'cast': 'Actor Three, Actor Four',
                'description': 'A touching drama about family and resilience.',
                'genres': ['Drama'],
                'languages': ['Hindi'],
                'poster_color': (13, 110, 253),
                'theater_name': 'Grand Hall 2',
                'trailer_url': 'https://www.youtube.com/watch?v=oHg5SJYRHA0',
            },
            {
                'name': 'Quantum Drift',
                'rating': 4.5,
                'cast': 'Actor Five, Actor Six',
                'description': 'A futuristic race to save a collapsing timeline.',
                'genres': ['Sci-Fi', 'Action'],
                'languages': ['English', 'Telugu'],
                'poster_color': (32, 201, 151),
                'theater_name': 'Neon Dome 3',
                'trailer_url': 'https://www.youtube.com/watch?v=zSWdZVtXT7E',
            },
            {
                'name': 'Laugh Riot',
                'rating': 4.1,
                'cast': 'Actor Seven, Actor Eight',
                'description': 'A comedy of errors during a chaotic wedding week.',
                'genres': ['Comedy'],
                'languages': ['Hindi'],
                'poster_color': (255, 193, 7),
                'theater_name': 'Laugh Arena 4',
                'trailer_url': 'https://www.youtube.com/watch?v=SOXWc32k4zA',
            },
            {
                'name': 'Shadow Line',
                'rating': 4.4,
                'cast': 'Actor Nine, Actor Ten',
                'description': 'A detective uncovers a city-wide conspiracy at midnight.',
                'genres': ['Thriller', 'Drama'],
                'languages': ['English', 'Tamil'],
                'poster_color': (108, 117, 125),
                'theater_name': 'Noir Screen 5',
                'trailer_url': 'https://www.youtube.com/watch?v=s7EdQ4FqbhY',
            },
            {
                'name': 'Midnight Manor',
                'rating': 4.0,
                'cast': 'Actor Eleven, Actor Twelve',
                'description': 'A family weekend in an old mansion turns terrifying.',
                'genres': ['Horror'],
                'languages': ['English'],
                'poster_color': (52, 58, 64),
                'theater_name': 'Haunt Hall 6',
                'trailer_url': 'https://www.youtube.com/watch?v=VVnf3Y6d87Y',
            },
            {
                'name': 'Love in Monsoon',
                'rating': 4.2,
                'cast': 'Actor Thirteen, Actor Fourteen',
                'description': 'Two strangers reconnect each rainy season across cities.',
                'genres': ['Romance', 'Drama'],
                'languages': ['Hindi', 'Marathi'],
                'poster_color': (233, 30, 99),
                'theater_name': 'Rainlight 7',
                'trailer_url': 'https://www.youtube.com/watch?v=K0eDlFX9GMc',
            },
            {
                'name': 'Pixel Pals',
                'rating': 4.3,
                'cast': 'Voice One, Voice Two',
                'description': 'Animated friends enter a game world to rescue their village.',
                'genres': ['Animation', 'Comedy'],
                'languages': ['English', 'Kannada'],
                'poster_color': (111, 66, 193),
                'theater_name': 'Family Screen 8',
                'trailer_url': 'https://www.youtube.com/watch?v=bLvqoHBptjg',
            },
            {
                'name': 'Blazing Wheels',
                'rating': 4.1,
                'cast': 'Actor Fifteen, Actor Sixteen',
                'description': 'Street racers unite to protect their neighborhood.',
                'genres': ['Action'],
                'languages': ['Telugu'],
                'poster_color': (255, 87, 34),
                'theater_name': 'Turbo Track 9',
                'trailer_url': 'https://www.youtube.com/watch?v=G62HrubdD6o',
            },
            {
                'name': 'Silent Verdict',
                'rating': 4.0,
                'cast': 'Actor Seventeen, Actor Eighteen',
                'description': 'A courtroom drama where one witness changes everything.',
                'genres': ['Drama', 'Thriller'],
                'languages': ['Marathi'],
                'poster_color': (121, 85, 72),
                'theater_name': 'Courtroom 10',
                'trailer_url': 'https://www.youtube.com/watch?v=x_7YlGv9u1g',
            },
            {
                'name': 'Cyber Frontier',
                'rating': 4.4,
                'cast': 'Actor Nineteen, Actor Twenty',
                'description': 'Hackers and heroes clash in a digital megacity.',
                'genres': ['Sci-Fi', 'Thriller'],
                'languages': ['Tamil'],
                'poster_color': (0, 188, 212),
                'theater_name': 'Cyberplex 11',
                'trailer_url': 'https://www.youtube.com/watch?v=vKQi3bBA1y8',
            },
            {
                'name': 'Street Circus',
                'rating': 3.9,
                'cast': 'Actor Twenty One, Actor Twenty Two',
                'description': 'A struggling troupe finds fame with one viral show.',
                'genres': ['Comedy', 'Drama'],
                'languages': ['Kannada'],
                'poster_color': (3, 169, 244),
                'theater_name': 'Carnival 12',
                'trailer_url': 'https://www.youtube.com/watch?v=1D6hM5_zVo8',
            },
            {
                'name': 'Dark Signal',
                'rating': 4.2,
                'cast': 'Actor Twenty Three, Actor Twenty Four',
                'description': 'A mysterious radio frequency predicts dangerous events.',
                'genres': ['Thriller', 'Horror'],
                'languages': ['Hindi'],
                'poster_color': (33, 37, 41),
                'theater_name': 'Signal Room 13',
                'trailer_url': 'https://www.youtube.com/watch?v=EXeTwQWrcwY',
            },
            {
                'name': 'Haunted Harbour',
                'rating': 4.0,
                'cast': 'Actor Twenty Five, Actor Twenty Six',
                'description': 'Ghost stories from a coastal town become dangerously real.',
                'genres': ['Horror', 'Drama'],
                'languages': ['Telugu'],
                'poster_color': (63, 81, 181),
                'theater_name': 'Dockside 14',
                'trailer_url': 'https://www.youtube.com/watch?v=YoHD9XEInc0',
            },
            {
                'name': 'Forever Summer',
                'rating': 4.3,
                'cast': 'Actor Twenty Seven, Actor Twenty Eight',
                'description': 'A feel-good romance set across one unforgettable summer.',
                'genres': ['Romance', 'Comedy'],
                'languages': ['English'],
                'poster_color': (255, 235, 59),
                'theater_name': 'Sunset Screen 15',
                'trailer_url': 'https://www.youtube.com/watch?v=TcMBFSGVi1c',
            },
            {
                'name': 'Cloud Racers',
                'rating': 4.2,
                'cast': 'Voice Three, Voice Four',
                'description': 'Animated pilots compete in sky races above floating cities.',
                'genres': ['Animation', 'Action'],
                'languages': ['Hindi', 'English'],
                'poster_color': (76, 175, 80),
                'theater_name': 'Skyview 16',
                'trailer_url': 'https://www.youtube.com/watch?v=eOrNdBpGMv8',
            },
        ]

        created_movies = 0
        created_theaters = 0
        created_seats = 0

        for movie_data in demo_movies:
            movie, movie_created = Movie.objects.get_or_create(
                name=movie_data['name'],
                defaults={
                    'rating': movie_data['rating'],
                    'cast': movie_data['cast'],
                    'description': movie_data['description'],
                    'trailer_url': movie_data['trailer_url'],
                },
            )

            movie_changed = False
            for field_name in ['rating', 'cast', 'description', 'trailer_url']:
                new_value = movie_data[field_name]
                if getattr(movie, field_name) != new_value:
                    setattr(movie, field_name, new_value)
                    movie_changed = True

            if movie_changed:
                movie.save(update_fields=['rating', 'cast', 'description', 'trailer_url'])

            if movie_created or not movie.image:
                self._attach_placeholder_poster(movie, movie_data['poster_color'])
                created_movies += 1 if movie_created else 0

            movie.genre.set(Genre.objects.filter(name__in=movie_data['genres']))
            movie.language.set(Language.objects.filter(name__in=movie_data['languages']))

            theater, theater_created = Theater.objects.get_or_create(
                name=movie_data['theater_name'],
                movie=movie,
                defaults={'time': timezone.now() + timedelta(hours=2)},
            )
            if theater_created:
                created_theaters += 1

            for row in ['A', 'B', 'C']:
                for seat_no in range(1, 7):
                    _, seat_created = Seat.objects.get_or_create(
                        theater=theater,
                        seat_number=f'{row}{seat_no}',
                        defaults={'is_booked': False},
                    )
                    if seat_created:
                        created_seats += 1

        self.stdout.write(self.style.SUCCESS(
            f'Seed complete. Movies added/updated: {len(demo_movies)}, '
            f'new movies: {created_movies}, new theaters: {created_theaters}, new seats: {created_seats}'
        ))

    def _attach_placeholder_poster(self, movie, color):
        image = Image.new('RGB', (600, 900), color=color)
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=90)
        buffer.seek(0)

        file_name = f'{movie.name.lower().replace(" ", "_")}_poster.jpg'
        movie.image.save(file_name, ContentFile(buffer.getvalue()), save=True)
