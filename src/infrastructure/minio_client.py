"""
MinIO / S3 客户端工具

文档上传、下载、列表、预签名 URL。
用于：
  - 知识库原始文档存储
  - 日志归档
  - 模型权重管理
  - 备份文件

启动方式 (独立运行):
  python -m src.infrastructure.minio_client upload --bucket agent-docs --file ./data/doc.pdf
  python -m src.infrastructure.minio_client download --bucket agent-docs --object doc.pdf
  python -m src.infrastructure.minio_client list --bucket agent-docs
"""

from __future__ import annotations

import argparse
import logging
import mimetypes
import os
import sys
from datetime import timedelta
from typing import List, Optional

from minio import Minio
from minio.error import S3Error

from src.config import settings

logger = logging.getLogger(__name__)


class MinioClient:
    """MinIO S3 客户端封装"""

    def __init__(
        self,
        endpoint: str = "",
        access_key: str = "",
        secret_key: str = "",
        secure: bool = False,
    ):
        self.endpoint = endpoint or settings.minio_endpoint
        self.access_key = access_key or settings.minio_access_key
        self.secret_key = secret_key or settings.minio_secret_key
        self.secure = secure or settings.minio_use_ssl

        self._client: Optional[Minio] = None

    @property
    def client(self) -> Minio:
        if self._client is None:
            self._client = Minio(
                endpoint=self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    # ------------------------------------------------------------------
    # Bucket 管理
    # ------------------------------------------------------------------

    def ensure_bucket(self, bucket_name: str) -> bool:
        """确保 Bucket 存在，不存在则创建"""
        try:
            if not self.client.bucket_exists(bucket_name):
                self.client.make_bucket(bucket_name)
                logger.info("Created bucket: %s", bucket_name)

                # 设置版本控制
                self.client.set_bucket_versioning(
                    bucket_name,
                    Minio._versioning_config(enabled=True),
                )
                logger.info("Enabled versioning on bucket: %s", bucket_name)
            return True
        except S3Error as e:
            logger.error("Failed to ensure bucket '%s': %s", bucket_name, e)
            return False

    def list_buckets(self) -> List[str]:
        """列出所有 Bucket"""
        return [b.name for b in self.client.list_buckets()]

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------

    def upload(
        self,
        bucket_name: str,
        object_name: str,
        file_path: str,
        content_type: str = "",
        metadata: Optional[dict] = None,
    ) -> str:
        """上传文件到 MinIO

        Returns:
            对象的 etag
        """
        if not content_type:
            content_type, _ = mimetypes.guess_type(file_path)
            content_type = content_type or "application/octet-stream"

        try:
            result = self.client.fput_object(
                bucket_name=bucket_name,
                object_name=object_name,
                file_path=file_path,
                content_type=content_type,
                metadata=metadata or {},
            )
            logger.info("Uploaded: %s/%s (etag=%s, size=%d)",
                        bucket_name, object_name, result.etag, os.path.getsize(file_path))
            return result.etag
        except S3Error as e:
            logger.error("Upload failed: %s/%s: %s", bucket_name, object_name, e)
            raise

    def download(
        self,
        bucket_name: str,
        object_name: str,
        output_path: str,
    ) -> str:
        """从 MinIO 下载文件

        Returns:
            本地文件路径
        """
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        try:
            self.client.fget_object(bucket_name, object_name, output_path)
            logger.info("Downloaded: %s/%s → %s", bucket_name, object_name, output_path)
            return output_path
        except S3Error as e:
            logger.error("Download failed: %s/%s: %s", bucket_name, object_name, e)
            raise

    def delete(
        self,
        bucket_name: str,
        object_name: str,
        recursive: bool = False,
    ) -> bool:
        """删除对象"""
        try:
            if recursive:
                objects = self.client.list_objects(bucket_name, prefix=object_name, recursive=True)
                for obj in objects:
                    self.client.remove_object(bucket_name, obj.object_name)
                logger.info("Recursively deleted: %s/%s/*", bucket_name, object_name)
            else:
                self.client.remove_object(bucket_name, object_name)
                logger.info("Deleted: %s/%s", bucket_name, object_name)
            return True
        except S3Error as e:
            logger.error("Delete failed: %s/%s: %s", bucket_name, object_name, e)
            return False

    def list_objects(
        self,
        bucket_name: str,
        prefix: str = "",
        recursive: bool = True,
    ) -> List[dict]:
        """列出对象"""
        objects = []
        try:
            for obj in self.client.list_objects(
                bucket_name, prefix=prefix, recursive=recursive
            ):
                objects.append({
                    "name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified.isoformat() if obj.last_modified else "",
                    "etag": obj.etag,
                    "is_dir": obj.is_dir,
                })
        except S3Error as e:
            logger.error("List failed: %s/%s: %s", bucket_name, prefix, e)
        return objects

    def presigned_get_url(
        self,
        bucket_name: str,
        object_name: str,
        expires_hours: int = 24,
    ) -> str:
        """生成预签名下载 URL (临时访问链接)"""
        try:
            return self.client.presigned_get_object(
                bucket_name,
                object_name,
                expires=timedelta(hours=expires_hours),
            )
        except S3Error as e:
            logger.error("Presigned URL generation failed: %s", e)
            return ""

    def presigned_put_url(
        self,
        bucket_name: str,
        object_name: str,
        expires_hours: int = 1,
    ) -> str:
        """生成预签名上传 URL"""
        try:
            return self.client.presigned_put_object(
                bucket_name,
                object_name,
                expires=timedelta(hours=expires_hours),
            )
        except S3Error as e:
            logger.error("Presigned upload URL generation failed: %s", e)
            return ""

    def stat(self, bucket_name: str, object_name: str) -> dict:
        """获取对象元数据"""
        try:
            result = self.client.stat_object(bucket_name, object_name)
            return {
                "name": result.object_name,
                "size": result.size,
                "last_modified": result.last_modified.isoformat() if result.last_modified else "",
                "etag": result.etag,
                "content_type": result.content_type,
                "metadata": result.metadata,
            }
        except S3Error:
            return {}

    # ------------------------------------------------------------------
    # 初始化所有必需 Bucket
    # ------------------------------------------------------------------

    def ensure_all_buckets(self) -> None:
        """确保所有预定义 Bucket 存在"""
        buckets = [
            settings.minio_bucket_docs,
            settings.minio_bucket_logs,
            settings.minio_bucket_models,
        ]
        for bucket in buckets:
            self.ensure_bucket(bucket)
        logger.info("All MinIO buckets ensured: %s", buckets)

    # ------------------------------------------------------------------
    # 备份专用
    # ------------------------------------------------------------------

    def backup_file(
        self,
        bucket_name: str,
        object_name: str,
        backup_prefix: str = "backups/",
    ) -> bool:
        """创建对象副本作为备份

        利用 MinIO 版本控制，也可以通过 CopyObject 创建命名副本。
        """
        try:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{backup_prefix}{timestamp}/{object_name}"

            self.client.copy_object(
                bucket_name,
                backup_name,
                f"/{bucket_name}/{object_name}",
            )
            logger.info("Backup created: %s → %s/%s", object_name, bucket_name, backup_name)
            return True
        except S3Error as e:
            logger.error("Backup failed: %s → %s: %s", object_name, bucket_name, e)
            return False


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="MinIO / S3 客户端工具")
    sub = parser.add_subparsers(dest="command")

    # upload
    p = sub.add_parser("upload")
    p.add_argument("--bucket", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--object", default="")

    # download
    p = sub.add_parser("download")
    p.add_argument("--bucket", required=True)
    p.add_argument("--object", required=True)
    p.add_argument("--output", default="")

    # list
    p = sub.add_parser("list")
    p.add_argument("--bucket", required=True)
    p.add_argument("--prefix", default="")

    # presign
    p = sub.add_parser("presign")
    p.add_argument("--bucket", required=True)
    p.add_argument("--object", required=True)
    p.add_argument("--hours", type=int, default=24)

    # init
    sub.add_parser("init")

    # delete
    p = sub.add_parser("delete")
    p.add_argument("--bucket", required=True)
    p.add_argument("--object", required=True)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    client = MinioClient()

    if args.command == "upload":
        client.ensure_bucket(args.bucket)
        object_name = args.object or os.path.basename(args.file)
        client.upload(args.bucket, object_name, args.file)

    elif args.command == "download":
        output = args.output or os.path.basename(args.object)
        client.download(args.bucket, args.object, output)

    elif args.command == "list":
        for obj in client.list_objects(args.bucket, args.prefix):
            print(f"{obj['name']:60s} {obj['size']:>10d}  {obj['last_modified']}")

    elif args.command == "presign":
        url = client.presigned_get_url(args.bucket, args.object, args.hours)
        print(url)

    elif args.command == "init":
        client.ensure_all_buckets()
        print("All buckets initialized.")

    elif args.command == "delete":
        client.delete(args.bucket, args.object)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
