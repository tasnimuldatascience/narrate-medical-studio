import zipfile

import pytest

from backend import extract


@pytest.mark.parametrize('body',[
    '<script>alert(1)</script>',
    '<foreignObject><div>active</div></foreignObject>',
    '<image href="https://example.invalid/image.png"/>',
    '<image href="file:///private/image.png"/>',
    '<image xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="//example.invalid/image.png"/>',
    '<style>@import "https://example.invalid/style.css";</style>',
    '<path style="fill:url(https://example.invalid/paint.svg#color)"/>',
    '<path fill="url(https://example.invalid/paint.svg#color)"/>',
    '<style>path { fill: u/**/rl(https://example.invalid/color); }</style>',
    r'<style>path { fill: u\72l(https://example.invalid/color); }</style>',
    '<use href="#shape" xml:base="https://example.invalid/"/>',
    '<set attributeName="href" to="https://example.invalid/"/>',
    '<path onload="alert(1)"/>',
])
def test_svg_rejects_active_and_external_features(tmp_path,body):
    source=tmp_path/'source.pptx'
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('ppt/presentation.xml','<presentation/>')
        archive.writestr('ppt/media/image.svg',
            '<svg xmlns="http://www.w3.org/2000/svg">'+body+'</svg>')
    with pytest.raises(ValueError,match='SVG with active or external'):
        extract.sanitize(source,tmp_path/'safe.pptx')


def test_svg_keeps_local_fragment_resources(tmp_path):
    source=tmp_path/'source.pptx'
    safe=tmp_path/'safe.pptx'
    svg=b'''<svg xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="paint"/><path id="shape" d="M0 0L10 10"/></defs>
      <style>path {fill:url('#paint');}</style>
      <use href="#shape" fill="url(#paint)"/>
    </svg>'''
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('ppt/presentation.xml','<presentation/>')
        archive.writestr('ppt/media/image.svg',svg)
    extract.sanitize(source,safe)
    with zipfile.ZipFile(safe) as archive:
        assert archive.read('ppt/media/image.svg')==svg


def test_svg_detected_by_declared_content_type(tmp_path):
    source=tmp_path/'source.pptx'
    with zipfile.ZipFile(source,'w') as archive:
        archive.writestr('ppt/presentation.xml','<presentation/>')
        archive.writestr('[Content_Types].xml',
            '<Types><Override PartName="/ppt/media/picture.bin" ContentType="image/svg+xml"/></Types>')
        archive.writestr('ppt/media/picture.bin',
            '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.invalid"/></svg>')
    with pytest.raises(ValueError,match='SVG with active or external'):
        extract.sanitize(source,tmp_path/'safe.pptx')
