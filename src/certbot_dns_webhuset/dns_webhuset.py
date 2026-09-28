"""Certbot plugin entry point."""

import logging

from certbot import errors
from certbot.plugins import dns_common

from .dns_api import DNSClient
from .mcp import MCPClient

logger = logging.getLogger(__name__)


class Authenticator(dns_common.DNSAuthenticator):
    description = "Obtain certificates using DNS TXT records through Webhuset's MCP API."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.credentials = None
        self.client = None
        self.pending = {}

    @classmethod
    def add_parser_arguments(cls, add, default_propagation_seconds=600):
        super().add_parser_arguments(add, default_propagation_seconds)
        add("credentials", help="Path to a Webhuset credentials INI file.")
        add("http-timeout", type=int, default=30, help="API/DNS request timeout in seconds.")

    def more_info(self):
        return "Creates and removes only the DNS-01 TXT values required by this Certbot run."

    def _setup_credentials(self):
        if self.conf("propagation-seconds") < 0 or self.conf("http-timeout") <= 0:
            raise errors.PluginError("Propagation must be >= 0 seconds; HTTP timeout must be > 0.")
        self.credentials = self._configure_credentials(
            "credentials",
            "Webhuset API credentials INI file",
            {"api-key": "a Webhuset API key"},
        )
        key = self.credentials.conf("api-key")
        if not isinstance(key, str) or key.startswith(("SETT_INN", "REPLACE_")):
            raise errors.PluginError("Set dns_webhuset_api_key to your Webhuset API key.")
        if "\r" in key or "\n" in key:
            raise errors.PluginError("The API key must be a single line.")
        self.client = DNSClient(
            MCPClient(key, self.conf("http-timeout")),
            zone_override=self.credentials.conf("zone"),
            timeout=self.conf("http-timeout"),
        )
        try:
            self.client.api.check_tools()
        except Exception:
            self.client.close()
            self.client = None
            raise

    def perform(self, achalls):
        try:
            # Uses Certbot's batch creation + one propagation wait for all records.
            return super().perform(achalls)
        except BaseException:
            self.cleanup(achalls)
            raise

    def _perform(self, domain, validation_name, validation):
        record, exists = self.client.prepare(validation_name, validation)
        if record in self.pending or exists:
            return
        # Track before the write so that an ambiguous timeout can also be cleaned up.
        self.pending[record] = None
        self.client.create(record)
        logger.info("Created Webhuset DNS challenge at %s (zone %s).", record.name, record.zone)

    def _cleanup(self, domain, validation_name, validation):
        # Only records this run attempted to add are candidates for deletion.
        for record in list(self.pending):
            if record.name == validation_name.lower().rstrip(".") and record.value == validation:
                self.client.delete(record)
                del self.pending[record]
                logger.info("Removed Webhuset DNS challenge at %s.", record.name)

    def cleanup(self, achalls):
        # Process every pending record even if one deletion fails, including partial perform().
        if not self.client:
            return
        try:
            for record in list(self.pending):
                try:
                    self._cleanup("", record.name, record.value)
                except errors.PluginError as exc:
                    logger.warning("Could not clean up TXT record at %s: %s", record.name, exc)
        finally:
            self.client.close()
            self.client = None
