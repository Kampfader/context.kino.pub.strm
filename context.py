import sys
import os
import re
import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon

# -------------------------------------------------------------------
# KINO.PUB ADDON HIJACKING (DAUERHAFT AKTIV)
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

# Unser eigenes Addon-Objekt
ADDON = _original_addon('context.kino.pub.strm')

def get_clean_title(title):
    """Trennt zweisprachige Titel und behält nur den Teil nach dem '/'."""
    if not title:
        return "Unbekannt"
    title = str(title)
    if '/' in title:
        title = title.split('/')[-1]
    return title.strip()

def sanitize_filename(name):
    """Entfernt ungültige Zeichen aus Dateinamen und Ordnern."""
    if not name:
        return "Unbekannt"
    return re.sub(r'[\\/*?:"<>|]', "", str(name)).strip()

def ensure_trailing_slash(path):
    """Macht Pfade sicher für Kodi VFS."""
    path = path.replace('\\', '/')
    if not path.endswith('/'):
        path += '/'
    return path

def delete_directory(path):
    """Löscht einen Ordner und alle darin enthaltenen Dateien rekursiv (Kodi VFS sicher)."""
    path = ensure_trailing_slash(path)
    dirs, files = xbmcvfs.listdir(path)
    for f in files:
        xbmcvfs.delete(path + f)
    for d in dirs:
        delete_directory(path + d)
    xbmcvfs.rmdir(path)

def create_strm_file(url, target_dir, filename):
    """Schreibt die .strm Datei in den Zielordner."""
    if not xbmcvfs.exists(target_dir):
        xbmcvfs.mkdirs(target_dir)
    filepath = os.path.join(target_dir, filename)
    try:
        f = xbmcvfs.File(filepath, 'w')
        f.write(url)
        f.close()
        return True
    except Exception as e:
        xbmc.log(f"[context.kino.pub.strm] Fehler beim Schreiben von {filepath}: {e}", xbmc.LOGERROR)
        return False

def export_single_item(item, movie_base, tv_base, bulk_mode=False):
    """
    Exportiert ein einzelnes Item. 
    Wenn bulk_mode=True, werden Dialoge ("Bereits exportiert") übersprungen und Dateien stumm aktualisiert.
    """
    count = 0

    # --- FALL A: Es ist eine klassische Serie ---
    if getattr(item, 'mediatype', '') == 'tvshow' or hasattr(item, 'seasons'):
        show_title = get_clean_title(item.title)
        show_dir_raw = os.path.join(tv_base, sanitize_filename(show_title))
        show_dir_safe = ensure_trailing_slash(show_dir_raw)
        
        if xbmcvfs.exists(show_dir_raw) or xbmcvfs.exists(show_dir_safe):
            if not bulk_mode:
                ret = xbmcgui.Dialog().select("Bereits exportiert", ["Abbrechen", "Aktualisieren (Neue hinzufügen)", "Serie komplett löschen"])
                if ret == 0 or ret == -1:
                    return 0, "tvshow"
                elif ret == 2:
                    delete_directory(show_dir_safe)
                    xbmcgui.Dialog().notification("Gelöscht", "Serie wurde entfernt.", xbmcgui.NOTIFICATION_INFO)
                    return 0, "tvshow"
        
        for season in item.seasons:
            season_num = season.index
            for episode in season.episodes:
                ep_num = episode.index
                ep_title = get_clean_title(episode.title or f"Episode {ep_num}")
                url = episode.url
                
                subfolder = os.path.join(sanitize_filename(show_title), f"Season {season_num:02d}")
                filename = f"{sanitize_filename(show_title)} - S{season_num:02d}E{ep_num:02d} - {sanitize_filename(ep_title)}.strm"
                target_dir = os.path.join(tv_base, subfolder)
                
                if create_strm_file(url, target_dir, filename):
                    count += 1
        return count, "tvshow"

    # --- FALL B: Es ist eine "Multi" Sammlung (Mehrteiler) ---
    elif hasattr(item, 'videos') and not getattr(item, 'mediatype', '') == 'movie':
        show_title = get_clean_title(item.title)
        show_dir_raw = os.path.join(tv_base, sanitize_filename(show_title))
        show_dir_safe = ensure_trailing_slash(show_dir_raw)
        
        if xbmcvfs.exists(show_dir_raw) or xbmcvfs.exists(show_dir_safe):
            if not bulk_mode:
                ret = xbmcgui.Dialog().select("Bereits exportiert", ["Abbrechen", "Aktualisieren", "Miniserie löschen"])
                if ret == 0 or ret == -1:
                    return 0, "multi"
                elif ret == 2:
                    delete_directory(show_dir_safe)
                    xbmcgui.Dialog().notification("Gelöscht", "Miniserie wurde entfernt.", xbmcgui.NOTIFICATION_INFO)
                    return 0, "multi"
        
        for video in item.videos:
            ep_num = video.index
            ep_title = get_clean_title(video.title or f"Teil {ep_num}")
            url = video.url
            
            subfolder = os.path.join(sanitize_filename(show_title), "Season 01")
            filename = f"{sanitize_filename(show_title)} - S01E{ep_num:02d} - {sanitize_filename(ep_title)}.strm"
            target_dir = os.path.join(tv_base, subfolder)
            
            if create_strm_file(url, target_dir, filename):
                count += 1
        return count, "multi"

    # --- FALL C: Es ist ein einzelner Film ---
    elif getattr(item, 'mediatype', '') == 'movie':
        title = get_clean_title(item.title)
        year = item.video_info.get("year", 0)
        url = item.url
        
        filename_base = f"{sanitize_filename(title)} ({year})" if year > 0 else sanitize_filename(title)
        filename = f"{filename_base}.strm"
        target_path = os.path.join(movie_base, filename)
        
        if xbmcvfs.exists(target_path):
            if not bulk_mode:
                ret = xbmcgui.Dialog().select("Bereits exportiert", ["Abbrechen", "Überschreiben", "Film löschen"])
                if ret == 0 or ret == -1:
                    return 0, "movie"
                elif ret == 2:
                    xbmcvfs.delete(target_path)
                    xbmcgui.Dialog().notification("Gelöscht", "Film wurde entfernt.", xbmcgui.NOTIFICATION_INFO)
                    return 0, "movie"
        
        if create_strm_file(url, movie_base, filename):
            count = 1
        return count, "movie"

    return 0, "unknown"


def main():
    movie_base = ADDON.getSetting('movies_path')
    tv_base = ADDON.getSetting('tvshows_path')
    
    if not movie_base or not tv_base:
        xbmcgui.Dialog().ok("Fehlende Pfade", "Bitte konfiguriere zuerst die Speicherorte für Filme und Serien in den Addon-Einstellungen.")
        ADDON.openSettings()
        return

    try:
        kino_addon = _original_addon("video.kino.pub")
        kino_path = xbmcvfs.translatePath(kino_addon.getAddonInfo("path"))
        sys.path.append(kino_path)
        
        from resources.lib.plugin import Plugin
        kino_plugin = Plugin()
    except Exception as e:
        xbmc.log(f"[context.kino.pub.strm] Kino.pub konnte nicht geladen werden: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Fehler", "kino.pub Plugin-Fehler.", xbmcgui.NOTIFICATION_ERROR)
        return

    listitem = sys.listitem
    item_id = listitem.getProperty("id")
    folder_id = listitem.getProperty("folder-id") # Wird vom Bookmark-Ordner gesendet

    # ==========================================
    # ROUTE 1: KOMPLETTER BOOKMARK-ORDNER EXPORT
    # ==========================================
    if folder_id:
        bg_dialog = xbmcgui.DialogProgressBG()
        bg_dialog.create("STRM Bulk Export", "Lese Lesezeichen-Ordner...")
        
        try:
            page = 1
            total_processed = 0
            
            # Alle Seiten des Ordners durchlaufen
            while True:
                response = kino_plugin.items.get(f"bookmarks/{folder_id}", data={"page": page})
                items_on_page = response.items
                
                for idx, simple_item in enumerate(items_on_page):
                    # Ladebalken aktualisieren
                    percent = int((idx / len(items_on_page)) * 100)
                    bg_dialog.update(percent, "STRM Bulk Export", f"Verarbeite: {get_clean_title(simple_item.title)}")
                    
                    try:
                        # Wir laden das volle Item herunter (um alle Staffeln/Links zu bekommen)
                        full_item = kino_plugin.items.instantiate_from_item_id(simple_item.item_id)
                        export_single_item(full_item, movie_base, tv_base, bulk_mode=True)
                        total_processed += 1
                    except Exception as e:
                        xbmc.log(f"[context.kino.pub.strm] Fehler bei Bulk-Item {simple_item.item_id}: {e}", xbmc.LOGERROR)
                
                pagination = response.pagination
                if pagination and int(pagination["current"]) < int(pagination["total"]):
                    page += 1
                else:
                    break
                    
            xbmcgui.Dialog().notification("Ordner Exportiert!", f"{total_processed} Medien synchronisiert.", xbmcgui.NOTIFICATION_INFO)
        except Exception as e:
            xbmc.log(f"[context.kino.pub.strm] Bulk Export Fehler: {e}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification("Fehler", "Ordner-Export abgebrochen.", xbmcgui.NOTIFICATION_ERROR)
        finally:
            bg_dialog.close()

    # ==========================================
    # ROUTE 2: EINZELNES ITEM EXPORTIEREN
    # ==========================================
    elif item_id:
        xbmcgui.Dialog().notification("STRM Export", "Lade Daten vom Server...", xbmcgui.NOTIFICATION_INFO)
        try:
            item = kino_plugin.items.instantiate_from_item_id(item_id)
        except Exception as e:
            xbmcgui.Dialog().notification("Fehler", "API fehlgeschlagen.", xbmcgui.NOTIFICATION_ERROR)
            return
            
        count, item_type = export_single_item(item, movie_base, tv_base, bulk_mode=False)
        
        if count > 0:
            if item_type == "movie":
                xbmcgui.Dialog().notification("Film Exportiert!", "Erfolgreich gespeichert.", xbmcgui.NOTIFICATION_INFO)
            else:
                xbmcgui.Dialog().notification("Serie Exportiert!", f"{count} Dateien gespeichert.", xbmcgui.NOTIFICATION_INFO)

    else:
        xbmcgui.Dialog().notification("Fehler", "Keine gültige ID gefunden.", xbmcgui.NOTIFICATION_ERROR)

if __name__ == '__main__':
    try:
        main()
    finally:
        # Erst GANZ AM ENDE räumen wir auf
        sys.argv[:] = original_argv
        xbmcaddon.Addon = _original_addon