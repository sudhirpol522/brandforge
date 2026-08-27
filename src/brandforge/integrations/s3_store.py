from __future__ import annotations

from typing import Any, cast

from ..exceptions import NotFoundError
from ..object_store import validate_object_key


class S3ObjectStore:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key_id: str | None,
        secret_access_key: str | None,
    ) -> None:
        import boto3

        kwargs: dict[str, Any] = {"region_name": region}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key_id:
            kwargs["aws_access_key_id"] = access_key_id
        if secret_access_key:
            kwargs["aws_secret_access_key"] = secret_access_key
        self.client = boto3.client("s3", **kwargs)
        self.bucket = bucket

    def put(self, key: str, content: bytes, media_type: str) -> str:
        safe_key = validate_object_key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=safe_key,
            Body=content,
            ContentType=media_type,
            ServerSideEncryption="AES256",
        )
        return safe_key

    def get(self, key: str) -> bytes:
        safe_key = validate_object_key(key)
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=safe_key)
            return cast(bytes, response["Body"].read())
        except self.client.exceptions.NoSuchKey as error:
            raise NotFoundError(f"object {safe_key} not found") from error
