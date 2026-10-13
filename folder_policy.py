"""Enforce the app's selected private Drive-folder authorization boundary."""

FILE_SCOPE = 'https://www.googleapis.com/auth/drive.file'
FOLDER_MIME = 'application/vnd.google-apps.folder'


def _identifier(value):
    # IDs are opaque; never interpolate path/query syntax into metadata requests.
    if (not isinstance(value, str) or not value or
            any(not (character.isascii() and (character.isalnum() or character in '_-'))
                for character in value)):
        raise ValueError('invalid selected folder binding')
    return value


def verify_selected_folders(config, account, metadata):
    """Check selected-root metadata and known destination chains before content I/O.

    Return False for legacy bindings, whose existing folder/document checks remain
    the caller's responsibility. ``metadata`` accepts only a configured folder ID.
    A destination with no explicit managed chain must be a direct child of root.
    Never discover or follow unknown parents returned by Drive.
    """
    access = config.get('folder_access')
    scopes = config.get('google_scopes')
    if access is None:
        if scopes is not None and FILE_SCOPE in scopes:
            raise ValueError('file-scoped authorization requires a selected folder binding')
        return False
    if access != 'selected_folder' or scopes != [FILE_SCOPE]:
        raise ValueError('selected folder authorization requires only drive.file')
    root = _identifier(config.get('archive_root_folder_id'))
    destinations = {_identifier(config.get('folder_id')),
                    _identifier(config.get('corrections_folder_id', config.get('folder_id')))}
    parents = config.get('managed_folder_parents', {})
    if not isinstance(parents, dict):
        raise ValueError('invalid managed folder binding')
    for child, parent in parents.items():
        _identifier(child)
        _identifier(parent)
        if child == root:
            raise ValueError('selected root cannot have a managed parent')
    # Validate all declared chains even if this publisher uses only some of them.
    for child in parents:
        seen = set()
        current = child
        while current != root:
            if current in seen or current not in parents:
                raise ValueError('managed folders must have a known rooted chain')
            seen.add(current)
            current = parents[current]
    expected = {}
    for destination in destinations:
        current = destination
        while current != root:
            parent = parents.get(current, root)
            expected[current] = parent
            current = parent
    # Root location and name are owner choices, not app-managed properties.
    for identifier in [root, *sorted(expected)]:
        item = metadata(identifier)
        if (not isinstance(item, dict) or item.get('id') != identifier or item.get('mimeType') != FOLDER_MIME or
                item.get('shared') or item.get('trashed') or
                not item.get('capabilities', {}).get('canEdit') or
                not any(owner.get('emailAddress', '').lower() == account.lower()
                        for owner in item.get('owners', []) if isinstance(owner, dict)) or
                (identifier != root and item.get('parents') != [expected[identifier]])):
            raise ValueError('selected archive folders must remain private, editable, owner-matched and rooted')
    return True
