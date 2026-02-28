"""
Telegram Bot Notification Module for P2Pool

Sends block found announcements to a Telegram group/channel.
Configuration is stored in data/<net>/telegram_config.json

Example config:
{
    "bot_token": "123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
    "chat_id": "-1001234567890",
    "enabled": true
}
"""

from __future__ import division

import json
import os
import time
import urllib
import urllib2

from twisted.internet import defer, threads
from twisted.python import log


class TelegramNotifier(object):
    """
    Telegram Bot notification handler for P2Pool.
    Sends block found messages to configured Telegram chat.
    """
    
    def __init__(self, datadir_path, net_name):
        self.datadir_path = datadir_path
        self.net_name = net_name
        self.config_file = os.path.join(datadir_path, 'telegram_config.json')
        self.config = self._load_config()
        self.last_message_time = 0
        self.rate_limit_seconds = 5  # Minimum seconds between messages
        
        if self.is_configured():
            print 'Telegram notifications enabled for chat %s' % self.config.get('chat_id', 'unknown')
        else:
            print 'Telegram notifications not configured (create %s)' % self.config_file
    
    def _load_config(self):
        """Load Telegram config from file."""
        if not os.path.exists(self.config_file):
            # Create example config file
            example_config = {
                "bot_token": "",
                "chat_id": "",
                "enabled": False,
                "error_notifications": False,
                "_comment": "Get bot_token from @BotFather, chat_id from @userinfobot or group ID. Set error_notifications=true to receive error reports."
            }
            try:
                with open(self.config_file, 'wb') as f:
                    f.write(json.dumps(example_config, indent=2))
                print 'Created example Telegram config: %s' % self.config_file
            except Exception as e:
                log.err(e, 'Error creating Telegram config file:')
            return example_config
        
        try:
            with open(self.config_file, 'rb') as f:
                config = json.loads(f.read())
            return config
        except Exception as e:
            log.err(e, 'Error loading Telegram config:')
            return {}
    
    def is_configured(self):
        """Check if Telegram is properly configured."""
        return (
            self.config.get('enabled', False) and
            self.config.get('bot_token') and
            self.config.get('chat_id')
        )
    
    def _send_message_sync(self, text, parse_mode='HTML'):
        """Send message synchronously (for use in thread)."""
        if not self.is_configured():
            return False
        
        bot_token = self.config['bot_token']
        chat_id = self.config['chat_id']
        
        url = 'https://api.telegram.org/bot%s/sendMessage' % bot_token
        
        data = urllib.urlencode({
            'chat_id': chat_id,
            'text': text.encode('utf-8'),
            'parse_mode': parse_mode,
            'disable_web_page_preview': 'true'
        })
        
        try:
            req = urllib2.Request(url, data)
            req.add_header('Content-Type', 'application/x-www-form-urlencoded')
            response = urllib2.urlopen(req, timeout=10)
            result = json.loads(response.read())
            return result.get('ok', False)
        except urllib2.HTTPError as e:
            error_body = e.read() if hasattr(e, 'read') else str(e)
            log.err(None, 'Telegram API error %d: %s' % (e.code, error_body))
            return False
        except Exception as e:
            log.err(e, 'Error sending Telegram message:')
            return False
    
    @defer.inlineCallbacks
    def send_message(self, text, parse_mode='HTML'):
        """Send message asynchronously."""
        if not self.is_configured():
            defer.returnValue(False)
        
        # Rate limiting
        now = time.time()
        if now - self.last_message_time < self.rate_limit_seconds:
            yield defer.succeed(None)
            defer.returnValue(False)
        
        self.last_message_time = now
        
        try:
            result = yield threads.deferToThread(self._send_message_sync, text, parse_mode)
            defer.returnValue(result)
        except Exception as e:
            log.err(e, 'Error in async Telegram send:')
            defer.returnValue(False)
    
    @defer.inlineCallbacks
    def announce_block_found(self, net_name, block_height, block_hash, miner_address, 
                              explorer_url, pool_hashrate=None, network_diff=None):
        """
        Send block found announcement to Telegram.
        
        Args:
            net_name: Network name (e.g., "DASH")
            block_height: Block height/number
            block_hash: Full block hash
            miner_address: Address of miner who found the block
            explorer_url: Full URL to block explorer
            pool_hashrate: Pool hashrate at time of find (optional)
            network_diff: Network difficulty (optional)
        """
        if not self.is_configured():
            defer.returnValue(False)
        
        # Format hashrate
        hashrate_str = ""
        if pool_hashrate:
            if pool_hashrate >= 1e12:
                hashrate_str = "%.2f TH/s" % (pool_hashrate / 1e12)
            elif pool_hashrate >= 1e9:
                hashrate_str = "%.2f GH/s" % (pool_hashrate / 1e9)
            elif pool_hashrate >= 1e6:
                hashrate_str = "%.2f MH/s" % (pool_hashrate / 1e6)
            else:
                hashrate_str = "%.2f H/s" % pool_hashrate
        
        # Build message
        message_lines = [
            u"\U0001F389 <b>%s BLOCK FOUND!</b> \U0001F389" % net_name.upper(),
            "",
            u"\U0001F4CA <b>Block:</b> #%s" % block_height,
            u"\U0001F464 <b>Miner:</b> <code>%s</code>" % miner_address,
        ]
        
        if hashrate_str:
            message_lines.append(u"\U000026A1 <b>Pool Hashrate:</b> %s" % hashrate_str)
        
        message_lines.extend([
            "",
            u"\U0001F517 <a href=\"%s\">View on Explorer</a>" % explorer_url,
        ])
        
        message = "\n".join(message_lines)
        
        result = yield self.send_message(message, parse_mode='HTML')
        
        if result:
            print 'Telegram: Block announcement sent successfully'
        else:
            print 'Telegram: Failed to send block announcement'
        
        defer.returnValue(result)
    
    @defer.inlineCallbacks
    def send_error_notification(self, error_text, error_type='Error'):
        """
        Send error notification to Telegram.
        
        Args:
            error_text: Error traceback or message
            error_type: Type of error (e.g., 'Error', 'Warning', 'Critical')
        """
        if not self.is_configured():
            defer.returnValue(False)
        
        # Check if error notifications are enabled (default: disabled for privacy)
        if not self.config.get('error_notifications', False):
            defer.returnValue(False)
        
        # Truncate very long error messages
        max_length = 4000  # Telegram message limit is 4096
        if len(error_text) > max_length:
            error_text = error_text[:max_length] + '\n\n... (truncated)'
        
        # Build message
        icon = u"\U000026A0" if error_type == 'Warning' else u"\U0001F6A8"
        message_lines = [
            u"%s <b>P2Pool %s</b>" % (icon, error_type),
            "",
            u"<pre>%s</pre>" % error_text.replace('<', '&lt;').replace('>', '&gt;'),
        ]
        
        message = "\n".join(message_lines)
        
        result = yield self.send_message(message, parse_mode='HTML')
        defer.returnValue(result)
    
    def reload_config(self):
        """Reload configuration from file."""
        self.config = self._load_config()
        return self.is_configured()
