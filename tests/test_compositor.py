from PIL import Image
import pytest

from backend.compositor import compose_slide, compose_title, STAGE


@pytest.mark.parametrize('size',[(1600,900),(1200,900),(600,1000)])
def test_compositor_preserves_source_extent_and_aspect(tmp_path,size):
    source=tmp_path/'source.png'
    image=Image.new('RGB',size,'#FFFFFF')
    # Colored corners make both cropping and placement errors observable.
    for x,y,color in [(0,0,'red'),(size[0]-40,0,'green'),
                      (0,size[1]-40,'blue'),(size[0]-40,size[1]-40,'yellow')]:
        image.paste(color,(x,y,x+40,y+40))
    image.save(source)
    output=compose_slide(source,tmp_path/'scene.png','Lesson title','Chapter title',2,3)
    with Image.open(output) as scene:
        assert scene.size==(1920,1080)
        ratio=min((STAGE[2]-STAGE[0])/size[0],(STAGE[3]-STAGE[1])/size[1])
        w,h=round(size[0]*ratio),round(size[1]*ratio)
        x=STAGE[0]+(STAGE[2]-STAGE[0]-w)//2
        y=STAGE[1]+(STAGE[3]-STAGE[1]-h)//2
        margin=max(2,int(10*ratio))
        assert scene.getpixel((x+margin,y+margin))==(255,0,0)
        assert scene.getpixel((x+w-1-margin,y+margin))==(0,128,0)
        assert scene.getpixel((x+margin,y+h-1-margin))==(0,0,255)
        assert scene.getpixel((x+w-1-margin,y+h-1-margin))==(255,255,0)


def test_compositor_validates_chapter_range(tmp_path):
    with pytest.raises(ValueError,match='Chapter number'):
        compose_slide('unused',tmp_path/'scene.png','Lesson','Chapter',0,4)


def test_title_card_handles_long_titles(tmp_path):
    path=compose_title(tmp_path/'title.png','An explanation with a long title '*7,
                       'A supplied subtitle, without additional clinical content.',3)
    with Image.open(path) as scene:
        assert scene.size==(1920,1080)
        assert scene.mode=='RGB'
