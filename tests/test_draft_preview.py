from PIL import Image

from scripts.render_draft_preview import banner


def test_draft_banner_covers_header_on_every_frame_without_changing_source():
    source=Image.new('RGB',(1920,1080),'white')
    first=banner(source)
    repeated=banner(first)
    assert source.getpixel((0,0))==(255,255,255)
    assert first.getpixel((0,60))==(128,48,45)
    assert first.getpixel((0,80))==(255,255,255)
    assert first.tobytes()==repeated.tobytes()
    assert first.crop((72,18,1300,68)).getextrema()[0]!=(128,128)
