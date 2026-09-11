"""Resolve native application fonts from the selected, read-only firmware."""
from pathlib import Path
import xml.etree.ElementTree as ET


def font_environment(firmware: Path, state: Path) -> dict[str, str]:
    font_dir = firmware / 'usr/share/fonts'
    if not font_dir.is_dir():
        raise RuntimeError('The selected firmware has no usr/share/fonts directory.')
    cache = state / 'font-cache'
    cache.mkdir(parents=True, exist_ok=True)
    root = ET.Element('fontconfig')
    ET.SubElement(root, 'dir').text = str(font_dir.resolve())
    ET.SubElement(root, 'cachedir').text = str(cache.resolve())
    for source, target in (('sans', 'sans-serif'), ('sans serif', 'sans-serif'),
                           ('mono', 'monospace')):
        match = ET.SubElement(root, 'match', target='pattern')
        ET.SubElement(ET.SubElement(match, 'test', name='family'), 'string').text = source
        ET.SubElement(ET.SubElement(match, 'edit', name='family', mode='assign'), 'string').text = target
    # conf.d contains absolute symlinks for the vehicle root. Reference the
    # mounted rule directly, without importing host/user font directories.
    cjk_rules = firmware / 'usr/share/fontconfig/conf.avail/56-noto-sans-cjk.conf'
    if cjk_rules.is_file():
        ET.SubElement(root, 'include').text = str(cjk_rules.resolve())
    # Named fonts still follow the firmware's UI/assets/fonts.conf. Only generic
    # families need defaults; all fallback glyphs also come from this image.
    for generic, family in (('sans-serif', 'Universal Sans Text 530'),
                            ('monospace', 'Universal Sans Mono Numerals Text 530')):
        alias = ET.SubElement(root, 'alias')
        ET.SubElement(alias, 'family').text = generic
        ET.SubElement(ET.SubElement(alias, 'prefer'), 'family').text = family
    config = state / 'firmware-fonts.conf'
    ET.ElementTree(root).write(config, encoding='utf-8', xml_declaration=True)
    return {'FONTCONFIG_FILE': str(config.resolve())}
