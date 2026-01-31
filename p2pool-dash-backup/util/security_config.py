# -*- coding: utf-8 -*-
"""
P2Pool Security Configuration Module

Provides centralized security configuration that can be tuned via config files.
Configuration is loaded from JSON files in the data directory.
"""

from __future__ import division

import json
import os
import time
import hashlib
import base64


# ==============================================================================
# DEFAULT SECURITY CONFIGURATION
# ==============================================================================

DEFAULT_CONFIG = {
    # Web authentication
    'web_auth_enabled': False,
    'web_auth_username': 'admin',
    'web_auth_password_hash': None,  # SHA256 hash of password
    
    # Rate limiting for web API
    'web_rate_limit_enabled': True,
    'web_requests_per_minute': 120,
    'web_burst_limit': 20,
    
    # Miner banning settings
    'ban_enabled': True,
    'ban_duration_seconds': 3600,  # 1 hour
    'max_violations_before_ban': 10,
    'max_connections_per_ip': 50,
    
    # Share submission rate limits
    'max_share_rate_per_worker': 5.0,  # shares per second
    'share_rate_window_seconds': 60,
    
    # DDoS detection thresholds
    'ddos_connection_rate_threshold': 10,  # connections per minute to trigger warning
    'ddos_high_share_rate_threshold': 2.0,  # shares/sec considered suspicious
    
    # IP whitelist (never ban these IPs)
    'ip_whitelist': ['127.0.0.1', '::1'],
    
    # Worker whitelist (never ban these workers)
    'worker_whitelist': [],
}


class SecurityConfig(object):
    """
    Singleton security configuration manager.
    Loads and saves security settings from/to JSON config file.
    """
    _instance = None
    
    def __new__(cls, datadir_path=None):
        if cls._instance is None:
            cls._instance = super(SecurityConfig, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, datadir_path=None):
        if self._initialized:
            return
        
        self._initialized = True
        self.datadir_path = datadir_path
        self.config_file = None
        self.config = dict(DEFAULT_CONFIG)
        self._last_load_time = 0
        self._reload_interval = 60  # Reload config every 60 seconds
        
        if datadir_path:
            self.config_file = os.path.join(datadir_path, 'security_config.json')
            self.load_config()
    
    def set_datadir(self, datadir_path):
        """Set the data directory path and load config"""
        self.datadir_path = datadir_path
        self.config_file = os.path.join(datadir_path, 'security_config.json')
        self.load_config()
    
    def load_config(self, silent=False):
        """Load configuration from JSON file
        
        Args:
            silent: If True, don't print log messages (used for periodic reloads)
        """
        if not self.config_file:
            return
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults (keeps new defaults if config file is old)
                    for key, value in loaded.items():
                        if key in self.config:
                            self.config[key] = value
                self._last_load_time = time.time()
                if not silent:
                    print '[SecurityConfig] Loaded configuration from %s' % self.config_file
            else:
                # Create default config file
                self.save_config()
                print '[SecurityConfig] Created default configuration at %s' % self.config_file
        except Exception as e:
            print '[SecurityConfig] Error loading config: %s' % e
    
    def save_config(self):
        """Save current configuration to JSON file"""
        if not self.config_file:
            return
        
        try:
            # Make config directory if needed
            config_dir = os.path.dirname(self.config_file)
            if not os.path.exists(config_dir):
                os.makedirs(config_dir)
            
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4, sort_keys=True)
            print '[SecurityConfig] Saved configuration to %s' % self.config_file
        except Exception as e:
            print '[SecurityConfig] Error saving config: %s' % e
    
    def maybe_reload(self):
        """Reload config if reload interval has passed (silent reload)"""
        if time.time() - self._last_load_time > self._reload_interval:
            self.load_config(silent=True)
    
    def get(self, key, default=None):
        """Get a configuration value"""
        self.maybe_reload()
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Set a configuration value and save"""
        self.config[key] = value
        self.save_config()
    
    # ==============================================================================
    # AUTHENTICATION HELPERS
    # ==============================================================================
    
    @staticmethod
    def hash_password(password):
        """Hash a password using SHA256"""
        return hashlib.sha256(password.encode('utf-8')).hexdigest()
    
    def set_web_password(self, username, password):
        """Set web authentication credentials"""
        self.config['web_auth_enabled'] = True
        self.config['web_auth_username'] = username
        self.config['web_auth_password_hash'] = self.hash_password(password)
        self.save_config()
    
    def disable_web_auth(self):
        """Disable web authentication"""
        self.config['web_auth_enabled'] = False
        self.save_config()
    
    def check_web_auth(self, username, password):
        """Check if credentials are valid"""
        if not self.config.get('web_auth_enabled', False):
            return True  # Auth disabled, allow all
        
        expected_user = self.config.get('web_auth_username', '')
        expected_hash = self.config.get('web_auth_password_hash', '')
        
        if not expected_hash:
            return True  # No password set, allow all
        
        return (username == expected_user and 
                self.hash_password(password) == expected_hash)
    
    def parse_basic_auth(self, auth_header):
        """Parse HTTP Basic Auth header and return (username, password) or (None, None)"""
        if not auth_header:
            return None, None
        
        try:
            if not auth_header.startswith('Basic '):
                return None, None
            
            encoded = auth_header[6:]
            decoded = base64.b64decode(encoded).decode('utf-8')
            username, password = decoded.split(':', 1)
            return username, password
        except:
            return None, None
    
    # ==============================================================================
    # WHITELIST HELPERS
    # ==============================================================================
    
    def is_ip_whitelisted(self, ip):
        """Check if IP is whitelisted"""
        return ip in self.config.get('ip_whitelist', [])
    
    def is_worker_whitelisted(self, worker):
        """Check if worker is whitelisted"""
        return worker in self.config.get('worker_whitelist', [])
    
    def add_ip_to_whitelist(self, ip):
        """Add IP to whitelist"""
        whitelist = self.config.get('ip_whitelist', [])
        if ip not in whitelist:
            whitelist.append(ip)
            self.config['ip_whitelist'] = whitelist
            self.save_config()
    
    def remove_ip_from_whitelist(self, ip):
        """Remove IP from whitelist"""
        whitelist = self.config.get('ip_whitelist', [])
        if ip in whitelist:
            whitelist.remove(ip)
            self.config['ip_whitelist'] = whitelist
            self.save_config()
    
    # ==============================================================================
    # CONFIG SUMMARY
    # ==============================================================================
    
    def get_config_summary(self):
        """Get a summary of current security configuration for display"""
        return {
            'web_auth_enabled': self.config.get('web_auth_enabled', False),
            'web_auth_username': self.config.get('web_auth_username', 'admin') if self.config.get('web_auth_enabled') else None,
            'web_rate_limit_enabled': self.config.get('web_rate_limit_enabled', True),
            'web_requests_per_minute': self.config.get('web_requests_per_minute', 120),
            'web_burst_limit': self.config.get('web_burst_limit', 20),
            'ban_enabled': self.config.get('ban_enabled', True),
            'ban_duration_seconds': self.config.get('ban_duration_seconds', 3600),
            'max_violations_before_ban': self.config.get('max_violations_before_ban', 10),
            'max_connections_per_ip': self.config.get('max_connections_per_ip', 50),
            'max_share_rate_per_worker': self.config.get('max_share_rate_per_worker', 5.0),
            'ip_whitelist_count': len(self.config.get('ip_whitelist', [])),
            'worker_whitelist_count': len(self.config.get('worker_whitelist', [])),
        }


# Global singleton instance (initialized without datadir, set later)
security_config = SecurityConfig()
