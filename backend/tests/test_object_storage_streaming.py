"""Object storage streaming contracts for large browser downloads."""

import unittest
from unittest.mock import patch

from backend.app.infrastructure.object_storage import stream_bytes


class _Response:
    headers = {"Content-Length": "6"}

    def __init__(self):
        self.closed = False
        self.released = False

    def stream(self, chunk_size):
        yield b"abc"
        yield b"def"

    def close(self):
        self.closed = True

    def release_conn(self):
        self.released = True


class ObjectStorageStreamingTests(unittest.TestCase):
    def test_stream_releases_the_minio_connection_after_iteration(self):
        response = _Response()
        with patch("backend.app.infrastructure.object_storage.object_storage.get_object", return_value=response):
            chunks, content_length = stream_bytes("s3://quant-artifacts/datasets/example.parquet")
            self.assertEqual(list(chunks), [b"abc", b"def"])

        self.assertEqual(content_length, "6")
        self.assertTrue(response.closed)
        self.assertTrue(response.released)


if __name__ == "__main__":
    unittest.main()
