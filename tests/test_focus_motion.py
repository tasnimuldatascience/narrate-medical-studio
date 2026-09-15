import pytest
from PIL import Image,ImageChops
from backend import focus_motion as focus,whiteboard


@pytest.mark.parametrize('rect',[(72,174,200,250),(1300,800,1432,912),(72,174,1432,912)])
def test_camera_keeps_source_and_region_inside_stage(rect):
    for amount in [0,.1,.5,1]:
        left,top,right,bottom=focus.camera_box(rect,amount)
        assert 0<=left<right<=1360 and 0<=top<bottom<=738
    left,top,right,bottom=focus.camera_box(rect,1)
    assert left<=rect[0]-72 and right>=rect[2]-72
    assert top<=rect[1]-174 and bottom>=rect[3]-174


def test_overview_restores_complete_original_pixels(tmp_path):
    path=tmp_path/'source.png';Image.new('RGB',(1200,900),'coral').save(path)
    cues=[{'label':'Original region','x':.5,'y':.5,'width':.3,'height':.2}]
    _,source,_,regions=whiteboard.prepare(path,'Lesson','Topic',1,1,cues)
    frame=focus.paint(source,cues,regions,1,0,1,overview=True)
    assert ImageChops.difference(frame.crop(whiteboard.STAGE),source.crop(whiteboard.STAGE)).getbbox() is None


def test_invalid_camera_progress_fails():
    with pytest.raises(ValueError):focus.camera_box((72,174,200,250),float('nan'))
