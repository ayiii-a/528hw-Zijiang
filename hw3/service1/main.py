import functions_framework
from google.cloud import storage

BUCKET = "528-zz-hw2"
bucket = storage.Client().bucket(BUCKET)   # authenticates as the function's service account


def requested_file(request):
    """Object name in the bucket: from the URL path for GET, from the payload for POST.
    A leading bucket name is dropped, so /528-zz-hw2/pages/1.html and /pages/1.html both work."""
    if request.method == "GET":
        name = request.path
    else:
        payload = request.get_json(silent=True)          # {"file": "pages/1.html"}
        name = payload.get("file") if isinstance(payload, dict) else request.form.get("file")   # file=pages/1.html
    name = (name or "").strip("/")
    if name.startswith(BUCKET + "/"):
        name = name[len(BUCKET) + 1:]
    return name


@functions_framework.http
def serve_file(request):
    name = requested_file(request)
    data = bucket.blob(name).download_as_bytes()
    return data, 200, {"Content-Type": "text/html; charset=utf-8"}