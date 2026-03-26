"""云端存储 Provider 抽象 (Phase 3)"""

from abc import ABC, abstractmethod
from typing import Optional

from .models import Experience


class CloudProvider(ABC):
    """云端存储 Provider 抽象基类"""

    name: str = ""

    @abstractmethod
    async def connect(self, **config) -> bool:
        """连接云端服务"""
        pass

    @abstractmethod
    async def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    async def upload_experience(self, exp: Experience) -> bool:
        """上传经验"""
        pass

    @abstractmethod
    async def download_experience(self, exp_id: str) -> Optional[Experience]:
        """下载经验"""
        pass

    @abstractmethod
    async def list_experiences(self, project: str) -> list[Experience]:
        """列出项目经验"""
        pass

    @abstractmethod
    async def search(self, query: str, project: str, top_k: int = 3) -> list[Experience]:
        """云端检索"""
        pass

    @abstractmethod
    async def sync_from_local(self, experiences: list[Experience]) -> dict:
        """从本地同步到云端"""
        pass

    @abstractmethod
    async def sync_to_local(self, project: str) -> list[Experience]:
        """从云端同步到本地"""
        pass


class SupabaseProvider(CloudProvider):
    """Supabase PostgreSQL Provider"""

    name = "supabase"

    def __init__(self):
        self.client = None
        self.url = None
        self.key = None

    async def connect(self, **config) -> bool:
        try:
            from supabase import create_client
            self.url = config.get("url")
            self.key = config.get("key")
            self.client = create_client(self.url, self.key)
            return True
        except Exception:
            return False

    async def disconnect(self):
        self.client = None

    async def upload_experience(self, exp: Experience) -> bool:
        if not self.client:
            return False
        try:
            data = {
                "id": exp.id,
                "project": exp.project,
                "type": exp.type.value,
                "level": exp.level.value,
                "title": exp.title,
                "problem": exp.problem,
                "solution": exp.solution,
                "metadata": {
                    "tech_stack": exp.metadata.tech_stack,
                    "problem_type": exp.metadata.problem_type,
                    "scene": exp.metadata.scene,
                    "keywords": exp.metadata.keywords,
                },
                "confidence": exp.confidence,
                "status": exp.status.value,
                "created_at": exp.created_at,
            }
            self.client.table("experiences").upsert(data).execute()
            return True
        except Exception:
            return False

    async def download_experience(self, exp_id: str) -> Optional[Experience]:
        if not self.client:
            return None
        try:
            result = self.client.table("experiences").select("*").eq("id", exp_id).execute()
            if result.data:
                return self._from_dict(result.data[0])
            return None
        except Exception:
            return None

    async def list_experiences(self, project: str) -> list[Experience]:
        if not self.client:
            return []
        try:
            result = self.client.table("experiences").select("*").eq("project", project).execute()
            return [self._from_dict(r) for r in result.data]
        except Exception:
            return []

    async def search(self, query: str, project: str, top_k: int = 3) -> list[Experience]:
        """Supabase 使用 PostgreSQL 全文搜索"""
        if not self.client:
            return []
        try:
            # 使用 PostgreSQL 的 to_tsvector 和 plainto_tsquery
            result = self.client.rpc(
                "search_experiences",
                {"query": query, "project_name": project, "limit": top_k}
            ).execute()
            return [self._from_dict(r) for r in result.data]
        except Exception:
            return []

    async def sync_from_local(self, experiences: list[Experience]) -> dict:
        """批量上传本地经验"""
        success = 0
        failed = 0
        for exp in experiences:
            if await self.upload_experience(exp):
                success += 1
            else:
                failed += 1
        return {"success": success, "failed": failed}

    async def sync_to_local(self, project: str) -> list[Experience]:
        """下载云端经验"""
        return await self.list_experiences(project)

    def _from_dict(self, d: dict) -> Experience:
        from .models import ExperienceMetadata, ExperienceType, ExperienceLevel, ExperienceStatus, ExperienceSource
        metadata = d.get("metadata", {})
        return Experience(
            id=d["id"],
            type=ExperienceType(d["type"]),
            level=ExperienceLevel(d["level"]),
            title=d["title"],
            tags=[],
            problem=d["problem"],
            solution=d["solution"],
            confidence=d.get("confidence", 0.8),
            status=ExperienceStatus(d.get("status", "active")),
            source=ExperienceSource(d.get("source", "agent")),
            created_at=d["created_at"],
            project=d.get("project", "default"),
            metadata=ExperienceMetadata(
                tech_stack=metadata.get("tech_stack", []),
                problem_type=metadata.get("problem_type", ""),
                scene=metadata.get("scene", []),
                keywords=metadata.get("keywords", []),
            ),
        )


class WeaviateProvider(CloudProvider):
    """Weaviate Provider - 仅使用 BM25，不存储向量"""

    name = "weaviate"

    def __init__(self):
        self.client = None

    async def connect(self, **config) -> bool:
        try:
            import weaviate
            self.client = weaviate.Client(
                url=config.get("url"),
                auth_client_secret=weaviate.AuthApiKey(config.get("api_key")) if config.get("api_key") else None
            )
            return self.client.is_ready()
        except Exception:
            return False

    async def disconnect(self):
        self.client = None

    async def upload_experience(self, exp: Experience) -> bool:
        if not self.client:
            return False
        try:
            data_object = {
                "id": exp.id,
                "project": exp.project,
                "type": exp.type.value,
                "level": exp.level.value,
                "title": exp.title,
                "problem": exp.problem,
                "solution": exp.solution,
                "confidence": exp.confidence,
                "status": exp.status.value,
                "created_at": exp.created_at,
            }
            # 明确禁用向量化，使用 "none" 向量化器
            self.client.data_object.create(
                data_object=data_object,
                class_name="Experience",
                vector=[0.0] * 100,  # 提供零向量避免自动生成
            )
            return True
        except Exception:
            return False

    async def download_experience(self, exp_id: str) -> Optional[Experience]:
        if not self.client:
            return None
        try:
            result = self.client.data_object.get_by_id(exp_id, class_name="Experience")
            if result:
                return self._from_dict(result["properties"])
            return None
        except Exception:
            return None

    async def list_experiences(self, project: str) -> list[Experience]:
        if not self.client:
            return []
        try:
            result = (
                self.client.query
                .get("Experience", ["id", "title", "problem", "solution", "type", "level", "confidence", "status", "created_at"])
                .with_where({
                    "path": ["project"],
                    "operator": "Equal",
                    "valueText": project,
                })
                .do()
            )
            return [self._from_dict(e) for e in result["data"]["Get"]["Experience"]]
        except Exception:
            return []

    async def search(self, query: str, project: str, top_k: int = 3) -> list[Experience]:
        """Weaviate 使用纯 BM25 搜索，禁用向量检索"""
        if not self.client:
            return []
        try:
            result = (
                self.client.query
                .get("Experience", ["id", "title", "problem", "solution", "type", "level", "confidence", "status", "created_at"])
                .with_bm25(query=query)  # 仅使用 BM25
                .with_where({
                    "path": ["project"],
                    "operator": "Equal",
                    "valueText": project,
                })
                .with_limit(top_k)
                .do()
            )
            return [self._from_dict(e) for e in result["data"]["Get"]["Experience"]]
        except Exception:
            return []

    async def sync_from_local(self, experiences: list[Experience]) -> dict:
        success = 0
        failed = 0
        for exp in experiences:
            if await self.upload_experience(exp):
                success += 1
            else:
                failed += 1
        return {"success": success, "failed": failed}

    async def sync_to_local(self, project: str) -> list[Experience]:
        return await self.list_experiences(project)

    def _from_dict(self, d: dict) -> Experience:
        from .models import ExperienceMetadata, ExperienceType, ExperienceLevel, ExperienceStatus, ExperienceSource
        return Experience(
            id=d["id"],
            type=ExperienceType(d.get("type", "feature")),
            level=ExperienceLevel(d.get("level", "L2")),
            title=d.get("title", ""),
            tags=[],
            problem=d.get("problem", ""),
            solution=d.get("solution", ""),
            confidence=d.get("confidence", 0.8),
            status=ExperienceStatus(d.get("status", "active")),
            source=ExperienceSource.AGENT,
            created_at=d.get("created_at", ""),
            project=d.get("project", "default"),
            metadata=ExperienceMetadata(),
        )


class ElasticsearchProvider(CloudProvider):
    """Elasticsearch Provider"""

    name = "elasticsearch"

    def __init__(self):
        self.client = None

    async def connect(self, **config) -> bool:
        try:
            from elasticsearch import AsyncElasticsearch
            self.client = AsyncElasticsearch(
                hosts=[config.get("host", "http://localhost:9200")],
                api_key=config.get("api_key"),
                basic_auth=(config.get("username"), config.get("password")) if config.get("username") else None
            )
            return await self.client.ping()
        except Exception:
            return False

    async def disconnect(self):
        if self.client:
            await self.client.close()
            self.client = None

    async def upload_experience(self, exp: Experience) -> bool:
        if not self.client:
            return False
        try:
            doc = {
                "id": exp.id,
                "project": exp.project,
                "type": exp.type.value,
                "level": exp.level.value,
                "title": exp.title,
                "problem": exp.problem,
                "solution": exp.solution,
                "metadata": {
                    "tech_stack": exp.metadata.tech_stack,
                    "keywords": exp.metadata.keywords,
                },
                "confidence": exp.confidence,
                "status": exp.status.value,
                "created_at": exp.created_at,
            }
            await self.client.index(index="experiences", id=exp.id, document=doc)
            return True
        except Exception:
            return False

    async def download_experience(self, exp_id: str) -> Optional[Experience]:
        if not self.client:
            return None
        try:
            result = await self.client.get(index="experiences", id=exp_id)
            if result["found"]:
                return self._from_dict(result["_source"])
            return None
        except Exception:
            return None

    async def list_experiences(self, project: str) -> list[Experience]:
        if not self.client:
            return []
        try:
            result = await self.client.search(
                index="experiences",
                query={"term": {"project": project}}
            )
            return [self._from_dict(h["_source"]) for h in result["hits"]["hits"]]
        except Exception:
            return []

    async def search(self, query: str, project: str, top_k: int = 3) -> list[Experience]:
        """ES 使用 BM25 搜索"""
        if not self.client:
            return []
        try:
            result = await self.client.search(
                index="experiences",
                query={
                    "bool": {
                        "must": [
                            {"multi_match": {"query": query, "fields": ["title^2", "problem", "solution", "metadata.keywords"]}},
                        ],
                        "filter": [
                            {"term": {"project": project}},
                            {"term": {"status": "active"}},
                        ]
                    }
                },
                size=top_k
            )
            return [self._from_dict(h["_source"]) for h in result["hits"]["hits"]]
        except Exception:
            return []

    async def sync_from_local(self, experiences: list[Experience]) -> dict:
        success = 0
        failed = 0
        for exp in experiences:
            if await self.upload_experience(exp):
                success += 1
            else:
                failed += 1
        return {"success": success, "failed": failed}

    async def sync_to_local(self, project: str) -> list[Experience]:
        return await self.list_experiences(project)

    def _from_dict(self, d: dict) -> Experience:
        from .models import ExperienceMetadata, ExperienceType, ExperienceLevel, ExperienceStatus, ExperienceSource
        metadata = d.get("metadata", {})
        return Experience(
            id=d["id"],
            type=ExperienceType(d.get("type", "feature")),
            level=ExperienceLevel(d.get("level", "L2")),
            title=d.get("title", ""),
            tags=[],
            problem=d.get("problem", ""),
            solution=d.get("solution", ""),
            confidence=d.get("confidence", 0.8),
            status=ExperienceStatus(d.get("status", "active")),
            source=ExperienceSource.AGENT,
            created_at=d.get("created_at", ""),
            project=d.get("project", "default"),
            metadata=ExperienceMetadata(
                tech_stack=metadata.get("tech_stack", []),
                keywords=metadata.get("keywords", []),
            ),
        )


class CloudSyncManager:
    """云端同步管理器"""

    PROVIDERS = {
        "supabase": SupabaseProvider,
        "weaviate": WeaviateProvider,
        "elasticsearch": ElasticsearchProvider,
    }

    def __init__(self):
        self._provider: Optional[CloudProvider] = None

    def create_provider(self, name: str) -> Optional[CloudProvider]:
        """创建 Provider 实例"""
        provider_class = self.PROVIDERS.get(name)
        if provider_class:
            return provider_class()
        return None

    async def connect(self, provider_name: str, **config) -> bool:
        """连接到云端"""
        self._provider = self.create_provider(provider_name)
        if self._provider:
            return await self._provider.connect(**config)
        return False

    async def disconnect(self):
        """断开连接"""
        if self._provider:
            await self._provider.disconnect()
            self._provider = None

    @property
    def is_connected(self) -> bool:
        return self._provider is not None

    async def upload(self, exp: Experience) -> bool:
        if not self._provider:
            return False
        return await self._provider.upload_experience(exp)

    async def download(self, exp_id: str) -> Optional[Experience]:
        if not self._provider:
            return None
        return await self._provider.download_experience(exp_id)

    async def sync_upload_all(self, experiences: list[Experience]) -> dict:
        """批量上传"""
        if not self._provider:
            return {"success": 0, "failed": len(experiences), "error": "Not connected"}
        return await self._provider.sync_from_local(experiences)

    async def sync_download_all(self, project: str) -> list[Experience]:
        """批量下载"""
        if not self._provider:
            return []
        return await self._provider.sync_to_local(project)

    async def search(self, query: str, project: str, top_k: int = 3) -> list[Experience]:
        """云端搜索"""
        if not self._provider:
            return []
        return await self._provider.search(query, project, top_k)
