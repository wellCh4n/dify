import json
import logging
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from elasticsearch import Elasticsearch
from flask import current_app
from pydantic import BaseModel, model_validator

from core.rag.datasource.entity.embedding import Embeddings
from core.rag.datasource.vdb.field import Field
from core.rag.datasource.vdb.vector_base import BaseVector
from core.rag.datasource.vdb.vector_factory import AbstractVectorFactory
from core.rag.datasource.vdb.vector_type import VectorType
from core.rag.models.document import Document
from extensions.ext_redis import redis_client
from models.dataset import Dataset

logger = logging.getLogger(__name__)


class ElasticSearchConfig(BaseModel):
    host: str
    port: int
    username: str
    password: str

    @model_validator(mode='before')
    def validate_config(cls, values: dict) -> dict:
        if not values['host']:
            raise ValueError("config HOST is required")
        if not values['port']:
            raise ValueError("config PORT is required")
        if not values['username']:
            raise ValueError("config USERNAME is required")
        if not values['password']:
            raise ValueError("config PASSWORD is required")
        return values


class ElasticSearchVector(BaseVector):
    def __init__(self, index_name: str, config: ElasticSearchConfig, attributes: list):
        super().__init__(index_name.lower())
        self._client = self._init_client(config)
        self._attributes = attributes

    def _init_client(self, config: ElasticSearchConfig) -> Elasticsearch:
        try:
            parsed_url = urlparse(config.host)
            print('#############', parsed_url)
            if parsed_url.scheme in ['http', 'https']:
                hosts = f'{config.host}:{config.port}'
            else:
                hosts = f'http://{config.host}:{config.port}'
            print('#############', hosts, config.username, config.password)
            client = Elasticsearch(
                hosts=hosts,
                basic_auth=(config.username, config.password),
                request_timeout=100000,
                retry_on_timeout=True,
                max_retries=10000,
            )
            print('############################', client.cluster.health())
        except requests.exceptions.ConnectionError:
            raise ConnectionError("Vector database connection error")

        return client

    def get_type(self) -> str:
        return 'elasticsearch'

    def add_texts(self, documents: list[Document], embeddings: list[list[float]], **kwargs):
        uuids = self._get_uuids(documents)
        for i in range(len(documents)):
            self._client.index(index=self._collection_name.lower(),
                               id=uuids[i],
                               document={
                                   Field.CONTENT_KEY.value: documents[i].page_content,
                                   Field.VECTOR.value: embeddings[i] if embeddings[i] else None,
                                   Field.METADATA_KEY.value: documents[i].metadata if documents[i].metadata else {}
                               })
        self._client.indices.refresh(index=self._collection_name.lower())
        return uuids

    def text_exists(self, id: str) -> bool:
        return self._client.exists(index=self._collection_name.lower(), id=id).__bool__()

    def delete_by_ids(self, ids: list[str]) -> None:
        for id in ids:
            self._client.delete(index=self._collection_name.lower(), id=id)

    def delete_by_metadata_field(self, key: str, value: str) -> None:
        query_str = {
            'query': {
                'match': {
                    f'metadata.{key}': f'{value}'
                }
            }
        }
        results = self._client.search(index=self._collection_name.lower(), body=query_str)
        ids = [hit['_id'] for hit in results['hits']['hits']]
        if ids:
            self.delete_by_ids(ids)

    def delete(self) -> None:
        self._client.indices.delete(index=self._collection_name.lower())

    def search_by_vector(self, query_vector: list[float], **kwargs: Any) -> list[Document]:
        top_k = kwargs.get("top_k", 10)
        query_str = {
            "query": {
                "knn": {
                    "field": Field.VECTOR.value,
                    "query_vector": query_vector,
                    "k": top_k
                }
            },
            "size": top_k
        }

        results = self._client.search(index=self._collection_name.lower(), body=query_str)

        docs_and_scores = []
        for hit in results['hits']['hits']:
            docs_and_scores.append(
                (Document(page_content=hit['_source'][Field.CONTENT_KEY.value],
                          vector=hit['_source'][Field.VECTOR.value],
                          metadata=hit['_source'][Field.METADATA_KEY.value]), hit['_score']))

        docs = []
        for doc, score in docs_and_scores:
            score_threshold = kwargs.get("score_threshold", .0) if kwargs.get('score_threshold', .0) else 0.0
            if score > score_threshold:
                doc.metadata['score'] = score
            docs.append(doc)

        return docs

    def search_by_full_text(self, query: str, **kwargs: Any) -> list[Document]:
        query_str = {
            "match": {
                Field.CONTENT_KEY.value: query
            }
        }
        results = self._client.search(index=self._collection_name.lower(), query=query_str)
        docs = []
        for hit in results['hits']['hits']:
            docs.append(Document(
                page_content=hit['_source'][Field.CONTENT_KEY.value],
                vector=hit['_source'][Field.VECTOR.value],
                metadata=hit['_source'][Field.METADATA_KEY.value],
            ))

        return docs

    def create(self, texts: list[Document], embeddings: list[list[float]], **kwargs):
        metadatas = [d.metadata for d in texts]
        self.create_collection(embeddings, metadatas)
        self.add_texts(texts, embeddings, **kwargs)

    def create_collection(
            self, embeddings: list, metadatas: Optional[list[dict]] = None, index_params: Optional[dict] = None
    ):
        lock_name = f'vector_indexing_lock_{self._collection_name.lower()}'
        with redis_client.lock(lock_name, timeout=20):
            collection_exist_cache_key = f'vector_indexing_{self._collection_name.lower()}'
            if redis_client.get(collection_exist_cache_key):
                logger.info(f"Collection {self._collection_name.lower()} already exists.")
                return

            if not self._client.indices.exists(index=self._collection_name.lower()):
                dim = len(embeddings[0])
                mappings = {
                    "properties": {
                        Field.CONTENT_KEY.value: {"type": "text"},
                        Field.VECTOR.value: {  # Make sure the dimension is correct here
                            "type": "dense_vector",
                            "dims": dim,
                            "similarity": "cosine"
                        },
                        Field.METADATA_KEY.value: {
                            "type": "object",
                            "properties": {
                                "doc_id": {"type": "keyword"}  # Map doc_id to keyword type
                            }
                        }
                    }
                }
                self._client.indices.create(index=self._collection_name.lower(), mappings=mappings)

            redis_client.set(collection_exist_cache_key, 1, ex=3600)


class ElasticSearchVectorFactory(AbstractVectorFactory):
    def init_vector(self, dataset: Dataset, attributes: list, embeddings: Embeddings) -> ElasticSearchVector:
        if dataset.index_struct_dict:
            class_prefix: str = dataset.index_struct_dict['vector_store']['class_prefix']
            collection_name = class_prefix
        else:
            dataset_id = dataset.id
            collection_name = Dataset.gen_collection_name_by_id(dataset_id)
            dataset.index_struct = json.dumps(
                self.gen_index_struct_dict(VectorType.ELASTICSEARCH, collection_name))

        config = current_app.config
        return ElasticSearchVector(
            index_name=collection_name,
            config=ElasticSearchConfig(
                host=config.get('ELASTICSEARCH_HOST'),
                port=config.get('ELASTICSEARCH_PORT'),
                username=config.get('ELASTICSEARCH_USERNAME'),
                password=config.get('ELASTICSEARCH_PASSWORD'),
            ),
            attributes=[]
        )
