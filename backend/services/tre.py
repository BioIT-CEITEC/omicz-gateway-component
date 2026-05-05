"""
TRE (Trusted Research Environment)
"""

def send_to_tre(zip_path: str) -> bool:
    """
    Upload the zip file to the TRE S3 bucket.
    """
    return True


def delete_zip(zip_path: str) -> bool:
    """
    Delete the local zip file after it has been confirmed in TRE.
    """
    return True
