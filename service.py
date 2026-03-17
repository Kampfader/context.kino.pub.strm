import sys
import os
import re
import time
import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon

# -------------------------------------------------------------------
# KINO.PUB ADDON HIJACKING
# -------------------------------------------------------------------
_original_addon = xbmcaddon.Addon
original_argv = sys.argv[:]

def patched_addon(id=None):
    if id is None:
        return _original_addon("video.kino.pub")
    return _original_addon(id)

xbmcaddon.Addon = patched_addon
sys.argv[:] = ["plugin://video.kino.pub/", "1", ""]
# -------------------------------------------------------------------

ADDON = _original_addon('context.kino.pub.strm')

def get_clean_title(title):
    if not title: return "Unbekannt"
    title = str(title)
    if '/' in title: title = title.split('/')[-1]
    return title.strip()

def sanitize_filename(name):
    if not name: return "Unbekannt"
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def ensure_trailing_slash(path):
    path = path.replace('\\', '/')
    if not path.endswith('/'): path += '/'
    return path

def delete_directory(path):
    path = ensure_trailing_slash(path)
    dirs, files = xbmcvfs.listdir(path)
    for f in files: xbmcvfs.delete(path + f)
    for d in dirs: delete_directory(path + d)
    xbmcvfs.rmdir(path)

def create_strm_file(url, target_dir, filename):
    if not xbmcvfs.exists(target_dir):
        xbmcvfs.mkdirs(target_dir)
    filepath = os.path.join(target_dir, filename)
    try:
        f = xbmcvfs.File(filepath, 'w')
        f.write(url)
        f.close()
    except:
        pass

def get_bookmark_folder_id(kino_plugin, folder_name):
    """Sucht die ID eines Lesezeichen-Ordners anhand seines Namens."""
    try:
        response = kino_plugin.client("bookmarks").get()
        for folder in response.get("items", []):
            if folder.get("title") == folder_name:
                return folder.get("id")
    except:
        pass
    return None

def process_bookmark_folder(kino_plugin, folder_id, movie_base, tv_base):
    """Exportiert alle Einträge im Ordner und gibt eine Liste der existierenden Titel zurück."""
    expected_movies = set()
    expected_shows = set()
    
    page = 1
    while True:
        try:
            response = kino_plugin.items.get(f"bookmarks/{folder_id}", data={"page": page})
            items_on_page = response.items
            
            for simple_item in items_on_page:
                try:
                    item = kino_plugin.items.instantiate_from_item_id(simple_item.item_id)
                    
                    # FALL: Serie oder Miniserie
                    if getattr(item, 'mediatype', '') == 'tvshow' or hasattr(item, 'seasons') or (hasattr(item, 'videos') and not getattr(item, 'mediatype', '') == 'movie'):
                        show_title = get_clean_title(item.title)
                        clean_folder_name = sanitize_filename(show_title)
                        expected_shows.add(clean_folder_name)
                        
                        # Alle Episoden stumm aktualisieren (Bulk)
                        if hasattr(item, 'seasons'): # Klassische Serie
                            for season in item.seasons:
                                for episode in season.episodes:
                                    url = episode.url
                                    subfolder = os.path.join(clean_folder_name, f"Season {season.index:02d}")
                                    filename = f"{clean_folder_name} - S{season.index:02d}E{episode.index:02d} - {sanitize_filename(get_clean_title(episode.title or str(episode.index)))}.strm"
                                    create_strm_file(url, os.path.join(tv_base, subfolder), filename)
                        elif hasattr(item, 'videos'): # Miniserie
                            for video in item.videos:
                                url = video.url
                                subfolder = os.path.join(clean_folder_name, "Season 01")
                                filename = f"{clean_folder_name} - S01E{video.index:02d} - {sanitize_filename(get_clean_title(video.title or str(video.index)))}.strm"
                                create_strm_file(url, os.path.join(tv_base, subfolder), filename)
                                
                    # FALL: Film
                    elif getattr(item, 'mediatype', '') == 'movie':
                        title = get_clean_title(item.title)
                        year = item.video_info.get("year", 0)
                        url = item.url
                        
                        filename_base = f"{sanitize_filename(title)} ({year})" if year > 0 else sanitize_filename(title)
                        filename = f"{filename_base}.strm"
                        expected_movies.add(filename)
                        
                        create_strm_file(url, movie_base, filename)
                except Exception as e:
                    xbmc.log(f"[STRM Sync] Fehler bei Item {simple_item.item_id}: {e}", xbmc.LOGWARNING)
            
            pagination = response.pagination
            if pagination and int(pagination["current"]) < int(pagination["total"]):
                page += 1
            else:
                break
        except Exception as e:
            xbmc.log(f"[STRM Sync] Fehler beim Abrufen der Seite {page}: {e}", xbmc.LOGERROR)
            break
            
    return expected_movies, expected_shows


def run_sync():
    movie_base = ADDON.getSetting('movies_path')
    tv_base = ADDON.getSetting('tvshows_path')
    movie_bookmark_name = ADDON.getSetting('movie_bookmark_name')
    tvshow_bookmark_name = ADDON.getSetting('tvshow_bookmark_name')
    
    if not movie_base or not tv_base:
        xbmc.log("[STRM Sync] Pfade nicht konfiguriert, breche ab.", xbmc.LOGINFO)
        return

    xbmcgui.Dialog().notification("STRM Sync", "Starte automatischen Abgleich...", xbmcgui.NOTIFICATION_INFO)

    try:
        kino_addon = _original_addon("video.kino.pub")
        sys.path.append(xbmcvfs.translatePath(kino_addon.getAddonInfo("path")))
        from resources.lib.plugin import Plugin
        kino_plugin = Plugin()
    except Exception as e:
        xbmc.log(f"[STRM Sync] kino.pub Plugin konnte nicht geladen werden: {e}", xbmc.LOGERROR)
        return

    all_expected_movies = set()
    all_expected_shows = set()

    # 1. Filme-Ordner synchronisieren
    if movie_bookmark_name:
        folder_id = get_bookmark_folder_id(kino_plugin, movie_bookmark_name)
        if folder_id:
            movies, shows = process_bookmark_folder(kino_plugin, folder_id, movie_base, tv_base)
            all_expected_movies.update(movies)
            all_expected_shows.update(shows)

    # 2. Serien-Ordner synchronisieren
    if tvshow_bookmark_name:
        folder_id = get_bookmark_folder_id(kino_plugin, tvshow_bookmark_name)
        if folder_id:
            movies, shows = process_bookmark_folder(kino_plugin, folder_id, movie_base, tv_base)
            all_expected_movies.update(movies)
            all_expected_shows.update(shows)

    # ==========================================
    # AUFRÄUMEN (Löschen, was nicht mehr da ist)
    # ==========================================
    # Filme aufräumen
    if xbmcvfs.exists(movie_base):
        _, files = xbmcvfs.listdir(movie_base)
        for f in files:
            if f.endswith('.strm') and f not in all_expected_movies:
                xbmcvfs.delete(os.path.join(movie_base, f))
                xbmc.log(f"[STRM Sync] Film gelöscht (nicht mehr im Lesezeichen): {f}", xbmc.LOGINFO)

    # Serien aufräumen
    if xbmcvfs.exists(tv_base):
        dirs, _ = xbmcvfs.listdir(tv_base)
        for d in dirs:
            if d not in all_expected_shows:
                delete_directory(os.path.join(tv_base, d))
                xbmc.log(f"[STRM Sync] Serie gelöscht (nicht mehr im Lesezeichen): {d}", xbmc.LOGINFO)

    # Zum Schluss die Kodi-Bibliothek aktualisieren, damit die gelöschten/neuen Sachen in der Oberfläche auftauchen
    xbmc.executebuiltin('UpdateLibrary(video)')
    xbmcgui.Dialog().notification("STRM Sync", "Synchronisation abgeschlossen!", xbmcgui.NOTIFICATION_INFO)


if __name__ == '__main__':
    monitor = xbmc.Monitor()
    
    # 20 Sekunden warten (abbrechen, falls Kodi vorher beendet wird)
    if not monitor.waitForAbort(20):
        # Nur ausführen, wenn der User es in den Settings aktiviert hat
        if ADDON.getSetting('sync_enabled') == 'true':
            try:
                run_sync()
            finally:
                sys.argv[:] = original_argv
                xbmcaddon.Addon = _original_addon