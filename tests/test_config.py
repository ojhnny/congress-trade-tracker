import pytest

from congress_trades.config import ConfigError, Settings

VALID_ENV = {
    "GCP_PROJECT_ID": "my-project",
    "GCS_RAW_BUCKET": "my-project-congress-raw",
    "HTTP_USER_AGENT": "congress-trades research me@example.com",
}


def test_reads_required_values_and_defaults():
    settings = Settings.from_env({**VALID_ENV, "STORAGE_BACKEND": "gcp"})

    assert settings.gcp_project_id == "my-project"
    assert settings.gcs_raw_bucket == "my-project-congress-raw"
    assert settings.bq_location == "US"
    assert settings.bq_raw_dataset == "raw"


def test_optional_values_override_defaults():
    settings = Settings.from_env({**VALID_ENV, "BQ_LOCATION": "us-central1"})

    assert settings.bq_location == "us-central1"


def test_local_backend_is_default_and_needs_no_gcp():
    settings = Settings.from_env({"HTTP_USER_AGENT": VALID_ENV["HTTP_USER_AGENT"]})

    assert settings.storage_backend == "local"
    assert settings.is_local


def test_lists_every_missing_variable():
    with pytest.raises(ConfigError) as err:
        Settings.from_env(
            {"STORAGE_BACKEND": "gcp", "GCP_PROJECT_ID": "my-project", "GCS_RAW_BUCKET": "  "}
        )

    message = str(err.value)
    assert "GCS_RAW_BUCKET" in message
    assert "HTTP_USER_AGENT" in message
    assert "GCP_PROJECT_ID" not in message


def test_user_agent_needs_contact_email():
    with pytest.raises(ConfigError, match="contact email"):
        Settings.from_env({**VALID_ENV, "HTTP_USER_AGENT": "congress-trades"})


def test_rejects_unknown_backend():
    with pytest.raises(ConfigError, match="STORAGE_BACKEND"):
        Settings.from_env({**VALID_ENV, "STORAGE_BACKEND": "s3"})
