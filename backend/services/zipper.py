import zipfile
import os


def create_zip(run_name: str, sequencer_location: str) -> str:
    """
    Zips all files inside the run folder, excluding any existing zip files.

    Folder structure:
        sequencer_location/run_name/          ← source folder
        sequencer_location/run_name/run_name.zip  ← output zip (inside the run folder)

    Returns the path to the created zip file.
    """
    run_folder = os.path.join(sequencer_location, run_name)
    zip_path = os.path.join(run_folder, f"{run_name}.zip")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for dirpath, dirnames, filenames in os.walk(run_folder):
            for filename in filenames:

                if filename.endswith('.zip'):
                    continue

                full_path = os.path.join(dirpath, filename)

                arcname = os.path.relpath(full_path, run_folder)

                zipf.write(full_path, arcname)

    return zip_path
