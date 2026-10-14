# Лише український словник (для виправлення літер після OCR): російський з стандартного хука не потрібен.
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = copy_metadata("pymorphy3_dicts_uk") + collect_data_files("pymorphy3_dicts_uk")
hiddenimports = ["pymorphy3_dicts_uk"]
