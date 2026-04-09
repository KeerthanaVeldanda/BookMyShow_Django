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
        ]
        languages = [
            'English',
            'Hindi',
            'Telugu',
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
