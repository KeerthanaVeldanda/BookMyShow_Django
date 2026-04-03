from django import template
from urllib.parse import parse_qs, urlparse
import re

register = template.Library()

YOUTUBE_VIDEO_ID_REGEX = re.compile(r'^[A-Za-z0-9_-]{11}$')
YOUTUBE_ALLOWED_HOSTS = {
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
    'www.youtu.be',
}

@register.filter(name='dict_lookup')
def dict_lookup(dict_obj, key):
    """
    Custom template filter to lookup values in a dictionary.
    Usage: {{ my_dict|dict_lookup:my_key }}
    """
    if dict_obj is None:
        return 0
    return dict_obj.get(key, 0)


@register.filter(name='youtube_embed_url')
def youtube_embed_url(url):
    if not url:
        return ''

    try:
        parsed = urlparse(str(url).strip())
    except (ValueError, AttributeError):
        return ''

    if parsed.scheme not in {'http', 'https'}:
        return ''

    host = parsed.netloc.lower().split(':')[0]
    if host not in YOUTUBE_ALLOWED_HOSTS:
        return ''

    video_id = ''
    if host in {'youtu.be', 'www.youtu.be'}:
        video_id = parsed.path.lstrip('/').split('/')[0]
    elif parsed.path == '/watch':
        video_id = parse_qs(parsed.query).get('v', [''])[0]
    elif parsed.path.startswith('/embed/'):
        video_id = parsed.path.split('/embed/', 1)[1].split('/')[0]
    elif parsed.path.startswith('/shorts/'):
        video_id = parsed.path.split('/shorts/', 1)[1].split('/')[0]

    if not video_id or not YOUTUBE_VIDEO_ID_REGEX.fullmatch(video_id):
        return ''

    return f'https://www.youtube-nocookie.com/embed/{video_id}?rel=0&modestbranding=1'
