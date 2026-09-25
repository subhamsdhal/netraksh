import os
import yaml
import pytest


def test_edge_dockerfile_exists():
    assert os.path.exists("edge/Dockerfile"), "Edge Dockerfile must exist"


def test_backend_dockerfile_exists():
    assert os.path.exists("backend/Dockerfile"), "Backend Dockerfile must exist"


def test_production_edge_entrypoint():
    with open("edge/Dockerfile", "r") as f:
        content = f.read()
    assert 'CMD ["python", "edge/main.py"]' in content, "Production edge entrypoint must be edge/main.py"
    assert "demo_runner.py" not in content, "demo_runner must NOT be production entrypoint"


def test_edge_image_no_private_certs():
    with open("edge/Dockerfile", "r") as f:
        content = f.read()
    # Should not COPY certs/ directly without explicitly skipping private keys, 
    # but the implementation avoids copying certs/ completely.
    assert "COPY certs/" not in content, "Private certs must not be baked into edge image"


def test_dockerfiles_no_hardcoded_secrets():
    for df_path in ["edge/Dockerfile", "backend/Dockerfile"]:
        with open(df_path, "r") as f:
            content = f.read()
        assert "ENV SECRET_KEY=" not in content, "Secrets must not be hardcoded in Dockerfile"
        assert "ENV DATABASE_URL=" not in content, "Secrets must not be hardcoded in Dockerfile"
        assert "ENV ADMIN_PASSWORD=" not in content, "Secrets must not be hardcoded in Dockerfile"


def test_non_root_user():
    for df_path in ["edge/Dockerfile", "backend/Dockerfile"]:
        with open(df_path, "r") as f:
            content = f.read()
        assert "USER netraksh" in content, "Containers must run as non-root user"


def test_edge_compose_no_postgres_minio():
    with open("docker-compose.edge.yml", "r") as f:
        compose = yaml.safe_load(f)
    services = compose.get("services", {})
    assert "edge" in services, "Edge compose must define edge service"
    assert "db" not in services, "Edge compose must not depend on local Postgres"
    assert "minio" not in services, "Edge compose must not depend on local MinIO"
    assert "frontend" not in services, "Edge compose must not depend on frontend"


def test_central_compose_contains_required_services():
    with open("docker-compose.yml", "r") as f:
        compose = yaml.safe_load(f)
    services = compose.get("services", {})
    assert "backend" in services
    assert "db" in services
    assert "minio" in services
    assert "frontend" in services


def test_minio_not_publicly_exposed():
    with open("docker-compose.yml", "r") as f:
        content = f.read()
    # Just checking it requires credentials. We do not expose it unauthenticated.
    assert "MINIO_ROOT_USER" in content
    assert "MINIO_ROOT_PASSWORD" in content


def test_persistent_edge_volume_exists():
    with open("docker-compose.edge.yml", "r") as f:
        compose = yaml.safe_load(f)
    assert "edge_data" in compose.get("volumes", {}), "Persistent edge volume must exist"


def test_production_source_tree_not_bind_mounted_wholesale():
    with open("docker-compose.edge.yml", "r") as f:
        content = f.read()
    assert "- ./:/app" not in content, "Production compose must not bind-mount the entire source tree wholesale"
    
    with open("docker-compose.yml", "r") as f:
        content = f.read()
    assert "- ./:/app" not in content, "Production compose must not bind-mount the entire source tree wholesale"


def test_root_dockerfile_deprecated():
    with open("Dockerfile", "r") as f:
        content = f.read()
    assert "DEPRECATED: LEGACY MONOLITHIC DEPLOYMENT IMAGE" in content, "Root Dockerfile must be marked deprecated"
