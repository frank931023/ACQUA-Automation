"""
========================================================================
  OnProjectOpen.py
  資料庫 51_MS_Teams_Rev05_SP2
========================================================================

⚠️ 這是從 ACQUA 資料庫解出來的**副本**,只是給你看的。
   改這裡不會影響 ACQUA。要真的改請用 ACQUA 自己的腳本編輯器 ——
   它會處理 ZIP 壓縮、FileSize、CRCValue、ChangeDate,
   少寫一個欄位 ACQUA 可能就讀不到、或靜默用舊版。

   來源:acqua.Files idFile=3 ・ 型別 FT_Script ・ 最後修改 2022-10-18 07:57:21

**開啟專案時**執行一次。

它在做什麼
    專案載入後的初始化。注意它跑在「開專案」這個動作裡 ——
    我們的 /api/open-project 會觸發它,所以開專案比想像中慢是正常的。

在 ACQUA 裡怎麼找到它
    資料庫   51_MS_Teams_Rev05_SP2
    專案     MS Teams v5 Rev05 SP2 - Handset

    這是**專案層級的掛鉤**,不掛在任何測項上,測項樹裡找不到。
    開啟上面那個專案 -> 專案層級的設定 / 腳本那一區,
    before / after / canceled / OnProjectOpen 都在那裡。

    執行時的副本在:
      C:\ACQUA_Files\File_Cache\51_MS_Teams_Rev05_SP2_<GUID>\OnProjectOpen.py

========================================================================
  以下是**原始程式碼**,一字未改。
========================================================================
"""
# -*- coding: utf-8 -*-
"""
Created on Dez 10 2019, 11:08

@author: LV
"""

# global packages
import glob
from pathlib import Path
import sys
import zipfile


def get_zip_file_path(filecache_path, zip_name):
    zip_path = Path(filecache_path) / f'{zip_name}'
    zip_path = glob.glob(str(zip_path))
    if len(zip_path) == 0:
        raise Exception(f'.zip folder \'{zip_name}\' not found')
    return zip_path


def unzip(zip_path, unzipped_folder_path):
    zip_path = zip_path[0]
    with zipfile.ZipFile(zip_path, 'r') as zip_obj:
        # Get a list of all archived file names from the zip
        list_of_file_names = zip_obj.namelist()
        # Iterate over the file names
        for file_name in list_of_file_names:
            # extract file if possible
            try:
                zip_obj.extract(file_name, unzipped_folder_path)
            except:
                continue


def remove_modules(zip_dict):
    """Removes the loaded HSL modules
        Note: The reload is only necessary prior to python v3.8
    """
    # delete loaded HSL modules -> enforces reload on next occurrence
    modules = sys.modules.copy()
    for module_name in modules.keys():
        if any(unzipped_folder_name in module_name for unzipped_folder_name in zip_dict.values()):
            del sys.modules[module_name]


def main(zip_package_dict):
    """Script for running on project open: removes previous loaded packages and unzips .zips which are located in the
    file cache

        Parameters
        ----------
        zip_package_dict : dict
            keys: zip archive names, e.g. HSL*.zip, values: name of unzipped folder, e.g. HSL

        Returns
        -------
        no returns
        """

    # zip_dict: keys: zip stems, values: name unzipped folder

    # remove previous loaded modules
    remove_modules(zip_package_dict)

    # unzip zips
    filecache_path = sys.path[-1] # Should be replaced with SubProject.Path as soon as SubProject.Path is reliable in all released ACQUA versions
    for zip_name, unzipped_folder_name in zip_package_dict.items():
        zip_path = get_zip_file_path(filecache_path, zip_name)
        unzipped_folder_path = Path(filecache_path) / unzipped_folder_name
        unzip(zip_path, unzipped_folder_path)


if __name__ == '__main__':
    zip_package_dict = {'HSL*.zip': 'HSL'}
    main(zip_package_dict)
    import HSL
