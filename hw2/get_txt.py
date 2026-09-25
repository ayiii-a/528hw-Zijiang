import os


def local_source(directory):
    names = sorted(n for n in os.listdir(directory) if n.endswith(".html"))
    def read(name):
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            return f.read()
    return names, read



def gcs_source(bucket_name, prefix):
    from google.cloud import storage    # only needed when reading from GCS
    client = storage.Client.create_anonymous_client()
    bucket = client.bucket(bucket_name)
    names = sorted(b.name[len(prefix):]
                   for b in client.list_blobs(bucket_name, prefix=prefix,
                                              fields="items(name),nextPageToken")  # names only: faster
                   if b.name.endswith(".html"))
    def read(name):
        return bucket.blob(prefix + name).download_as_text()
    return names, read


