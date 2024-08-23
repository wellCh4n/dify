#!/bin/bash
set -x

pytest api/tests/integration_tests/vdb/elasticsearch \
  api/tests/integration_tests/vdb/test_vector_store.py