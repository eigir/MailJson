import base64
import csv
import datetime
import email
import re
from io import StringIO

# ---------------------------------------------------------------------
#  (c) 2013 Newsman App, https://github.com/Newsman/MailToJson
#  (c) 2015 Mike Andersen, mike@geekpod.net
#  This code is released under MIT license.
# ---------------------------------------------------------------------

# regular expresion from https://github.com/django/django/blob/master/django/core/validators.py

email_re = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
    # quoted-string, see also http://tools.ietf.org/html/rfc2822#section-3.2.5
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"'
    r')@((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)$)'  # domain
    r'|\[(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}\]$', re.IGNORECASE)

email_extract_re = re.compile("<(([.0-9a-z_+-=]+)@(([0-9a-z-]+\.)+[0-9a-z]{2,9}))>", re.M | re.S | re.I)
filename_re = re.compile("filename=\"(.+)\"|filename=([^;\n\r\"\']+)", re.I | re.S)

begin_tab_re = re.compile("^\t+", re.M)
begin_space_re = re.compile("^\s+", re.M)


class MailJson(object):
    """class to convert between json and mail format"""

    def __init__(self, d):
        self.json_data = {}
        self.mail = None
        self.encoding = "utf-8"
        self.raw_parts = []

        if type(d) is email.message.Message:
            self.mail = d
            self.json_data = self.parse_mail(d)
        elif type(d) is dict:
            raise NotImplementedError('Conversion from JSON to mail, is not yet implemented')
            # TODO: Convert json to email.message.Message object
        else:
            raise TypeError('Unknown data-type passed')

    def _decode_headers(self, v):
        if type(v) is not list:
            v = [v]

        ret = []
        for h in v:
            h = email.header.decode_header(h)
            h_ret = []
            for h_decoded in h:
                hv = h_decoded[0]
                hv = str(hv).strip().strip("\t")
                h_ret.append(hv.encode(self.encoding))
            ret.append(h_ret)
        return ret

    def _get_part_headers(self, part):
        # raw headers
        headers = {}
        for k in part.keys():
            k = k.lower()
            v = part.get_all(k)
            v = self._decode_headers(v)

            if len(v) == 1:
                headers[k] = v[0]
            else:
                headers[k] = v
        return headers

    @staticmethod
    def _parse_date(v):
        if v is None:
            return datetime.datetime.now()
        if type(v) is list:
            v = str(v[0], 'ascii')
        tt = email.utils.parsedate_tz(v)
        if tt is None:
            return datetime.datetime.now()
        timestamp = email.utils.mktime_tz(tt)
        date = datetime.datetime.fromtimestamp(timestamp)
        return date

    @staticmethod
    def _fix_encoded_subject(subject):
        if subject is None:
            return ""
        subject = "%s" % subject
        subject = subject.strip()

        if len(subject) < 2:
            # empty string or not encoded string ?
            return subject
        if subject.find("\n") == -1:
            # is on single line
            return subject
        if subject[0:2] != "=?":
            # not encoded
            return subject

        subject = subject.replace("\r", "")
        subject = begin_tab_re.sub("", subject)
        subject = begin_space_re.sub("", subject)
        lines = subject.split("\n")

        new_subject = ""
        for l in lines:
            new_subject = "%s%s" % (new_subject, l)
            if l[-1] == "=":
                new_subject = "%s\n " % new_subject
        return new_subject

    @staticmethod
    def _extract_email(s):
        ret = email_extract_re.findall(s)
        if len(ret) < 1:
            p = s.split(" ")
            for e in p:
                e = e.strip()
                if email_re.match(e):
                    return e
            return None
        else:
            return ret[0][0]

    def _parse_recipients(self, v):
        if v is None:
            return None
        ret = []

        # Sometimes a list is passed, which breaks .replace()
        if isinstance(v, list):
            v = b",".join(v)
        v = str(v, 'UTF8')
        v = v.replace("\n", " ").replace("\r", " ").strip()
        s = StringIO(v)
        c = csv.reader(s)
        try:
            row = c.__next__()
        except StopIteration:
            return ret

        for entry in row:
            entry = entry.strip()
            if email_re.match(entry):
                e = entry
                entry = ""
            else:
                e = self._extract_email(entry)
                entry = entry.replace("<%s>" % e, "")
                entry = entry.strip()
                if e and entry.find(e) != -1:
                    entry = entry.replace(e, "").strip()
            # If all else has failed
            if entry and e is None:
                e_split = entry.split(" ")
                e = e_split[-1].replace("<", "").replace(">", "")
                entry = " ".join(e_split[:-1])

            ret.append({"name": entry, "email": e})
        return ret

    @staticmethod
    def _get_content_charset(part, failobj=None):
        """Return the charset parameter of the Content-Type header.

        The returned string is always coerced to lower case.  If there is no
        Content-Type header, or if that header has no charset parameter,
        failobj is returned.
        """
        missing = object()
        charset = part.get_param("charset", missing)
        if charset is missing:
            return failobj
        if isinstance(charset, tuple):
            # RFC 2231 encoded, so decode it, and it better end up as ascii.
            pcharset = charset[0] or "us-ascii"
            try:
                # LookupError will be raised if the charset isn't known to
                # Python.  UnicodeError will be raised if the encoded text
                # contains a character not in the charset.
                charset = str(charset[2], pcharset).encode("us-ascii")
            except (LookupError, UnicodeError):
                charset = charset[2]
        # charset character must be in us-ascii range
        try:
            if isinstance(charset, str):
                charset = charset.encode("us-ascii")
            charset = str(charset, "us-ascii").encode("us-ascii")
        except UnicodeError:
            return failobj
        # RFC 2046, $4.1.2 says charsets are not case sensitive
        return charset.lower()

    def parse_mail(self, msg):
        headers = self._get_part_headers(msg)
        self.json_data["headers"] = headers
        self.json_data["datetime"] = self._parse_date(headers.get("date", None)).strftime("%Y-%m-%d %H:%M:%S")
        self.json_data["subject"] = self._fix_encoded_subject(headers.get("subject", None))
        self.json_data["to"] = self._parse_recipients(headers.get("to", None))
        self.json_data["from"] = self._parse_recipients(headers.get("from", None))
        self.json_data["cc"] = self._parse_recipients(headers.get("cc", None))

        attachments = []
        parts = []
        for part in msg.walk():
            if part.is_multipart():
                continue

            content_disposition = part.get("Content-Disposition", None)
            if content_disposition:
                # we have attachment
                r = filename_re.findall(content_disposition)
                if r:
                    filename = sorted(r[0])[1]
                else:
                    filename = "undefined"

                a = {"filename": filename, "content": base64.b64encode(part.get_payload(decode=True)),
                     "content_type": part.get_content_type()}
                attachments.append(a)
            else:
                try:
                    p = {"content_type": part.get_content_type(),
                         "content": str(part.get_payload(decode=1),
                                        self._get_content_charset(part, "utf-8").decode(),
                                        "ignore").encode(self.encoding),
                         "headers": self._get_part_headers(part)}
                    parts.append(p)
                    self.raw_parts.append(part)
                except LookupError:
                    # Sometimes an encoding isn't recognised - not much to be done
                    pass

        self.json_data["attachments"] = attachments
        self.json_data["parts"] = parts
        self.json_data["encoding"] = self.encoding

        # print("debug break")

        return self.json_data
