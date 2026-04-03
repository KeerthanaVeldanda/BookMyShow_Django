from django.test import TestCase
from django.core.exceptions import ValidationError

from .models import validate_youtube_trailer_url
from .templatetags.custom_filters import youtube_embed_url

# Create your tests here.


class TrailerValidationTests(TestCase):
	def test_valid_youtube_watch_url_passes(self):
		validate_youtube_trailer_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ')

	def test_non_youtube_url_fails(self):
		with self.assertRaises(ValidationError):
			validate_youtube_trailer_url('https://example.com/watch?v=dQw4w9WgXcQ')

	def test_javascript_scheme_fails(self):
		with self.assertRaises(ValidationError):
			validate_youtube_trailer_url('javascript:alert(1)')


class TrailerTemplateFilterTests(TestCase):
	def test_embed_url_is_constructed_from_video_id_only(self):
		embed = youtube_embed_url('https://youtu.be/dQw4w9WgXcQ')
		self.assertEqual(
			embed,
			'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?rel=0&modestbranding=1',
		)

	def test_invalid_or_malicious_url_returns_empty_string(self):
		self.assertEqual(youtube_embed_url('https://evil.com/xss'), '')
		self.assertEqual(youtube_embed_url('javascript:alert(1)'), '')
