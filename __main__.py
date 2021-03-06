#!/usr/bin/env python

import smtplib, tempfile
from PPFilter import *
import syslog, os, sys, pwd
import ppsmtpd, socket
import threading, signal
import setproctitle as spc

title = 'PPFilter (idle)'

syslog.openlog('ppfilter', syslog.LOG_PID|syslog.LOG_NOWAIT, syslog.LOG_MAIL)

spc.setproctitle(title)

class NonRootException(Exception): pass

class SendingBackException(Exception): pass

class SMTPD(ppsmtpd.SMTPServer):

    message  = None

    def process_message(self, mail_from, rcpts_to, message_data):

        spc.setproctitle('PPFilter (processing)')
        self.message_data = message_data
        filepath = None

        try:
            self.message = {'mailfrom': mail_from, 'rcpts': rcpts_to, 'data': message_data}
            filepath = enqueuer.enqueue(self.message)
            if filepath != None:
                sc = default.DefaultFilter(filepath)
                spc.setproctitle('PPFilter (scanning)')
                sc.scan()
                self.send_back(filepath)

        except enqueuer.QueueException, e:
            return "451 Requested action aborted: %s" % (e.message)

        except scanner.ContentFilterException, e:
            return "451 Requested action aborted: %s" % (e.message)

        except scanner.ContentFilterVirusException, e:
            return

        except SendingBackException, e:
            return e.message

        except scanner.ContentFilterSpamException, e:
            if config.spam_final_action == "tag":
                msg = message.Message(filepath)
                eml = msg.get_message()
                eml.add_header("X-Spam-Status", "Spam, score: %s" % (e) )
                msg.write_message()
                try:
                    self.send_back(filepath)
                    spc.setproctitle('PPFilter (idle)')
                except SendingBackException, e:
                    return e.message

            elif config.spam_final_action == "discard":
                pass

        finally:
            spc.setproctitle('PPFilter (idle)')
            if os.path.exists(filepath):
                os.unlink(filepath)

    def send_back(self, filepath):
        try:
            client = smtplib.SMTP(config.reinject_address, config.reinject_port)
            response = client.sendmail(self.message['mailfrom'], self.message['rcpts'], open(filepath).read())
            os.unlink(filepath)
            for rcpt in self.message['rcpts']:
                syslog.syslog('from=%s, to=%s, relay=%s:%s, status=sent (%s)' % (self.message['mailfrom'], rcpt, config.reinject_address, str(config.reinject_port), response[1]) )

            return

        except Exception, e:
            raise SendingBackException('451 '+ e.message)

def run_as_user(user):
    if os.getuid() != 0:
        raise NonRootException('this program must to be started as root')

    user_info = pwd.getpwnam(config.run_user)
    uid = user_info[2]
    os.setuid(uid)

def do_sanity_check():
    if not os.path.exists(config.temp_directory):
        os.mkdir(config.temp_directory)

if __name__ == "__main__":

    try:

        run_as_user(config.run_user)

        do_sanity_check()

        HOST, PORT = config.listen_address, config.listen_port

        syslog.syslog("starting Python Policy Filter (%s, %s)" % (HOST, PORT))
        server = SMTPD( (HOST, int(PORT)), ppsmtpd.SMTPRequestHandler)
        server.daemon_threads = True
        server.allow_reuse_address = True
        ip, port = server.server_address

        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.start()

    except NonRootException, e:
        print e
        syslog.closelog()

    except KeyboardInterrupt:
        syslog.syslog("stopping Python Policy Filter (%s, %s)" % (address, port))
        syslog.closelog()
