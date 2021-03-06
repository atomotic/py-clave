import json
import xml.etree.ElementTree as ET
import re
import os

from threading import Thread
import tornado.web
import tornado.ioloop as IOLoop

from epub.utils import EPUB
from epub.utils import listFiles

from data.utils import opendb
from data import opds


class GeneralErrorHandler(tornado.web.RequestHandler):
    def __init__(self, application, request, status_code):
        tornado.web.RequestHandler.__init__(self, application, request)
        self.set_status(status_code)

    def write_error(self, status, **kwargs):
        self.write("Bad request")

    def prepare(self):
        raise tornado.web.HTTPError(400)


class GetInfo(tornado.web.RequestHandler):

    @tornado.web.asynchronous
    def get(self, filename):
        if filename:

            try:
                self.thread = Thread(target=self.querydb, args=(self.on_callback, filename,))
                self.thread.start()
            except IOError:
                raise tornado.web.HTTPError(404)
        else:
            raise tornado.web.HTTPError(400)

    def querydb(self, callback, isbn):
        database, conn = opendb()

        try:
            path = database.execute("SELECT path FROM books WHERE isbn = '{0}' ".format(isbn)).fetchone()["path"]
        except TypeError:
            tornado.ioloop.IOLoop.instance().add_callback(lambda: callback("Nope."))
            raise tornado.web.HTTPError(404)
        finally:
            conn.close()

        output = EPUB(path).meta
        tornado.ioloop.IOLoop.instance().add_callback(lambda: callback(output))

    def on_callback(self, output):
        self.write(output)
        self.flush()
        self.finish()


class ListFiles(tornado.web.RequestHandler):

    def get(self):
        response = listFiles()
        dump = json.JSONEncoder().encode(response)
        self.set_header("Content-Type", "application/json")
        self.write(dump)


class ShowFileToc(tornado.web.RequestHandler):

    @tornado.web.asynchronous
    def get(self, identifier):
        if identifier:
            try:
                self.thread = Thread(target=self.perform, args=(self.on_callback, identifier,))
                self.thread.start()
            except IOError:
                raise tornado.web.HTTPError(404)
        else:
            raise tornado.web.HTTPError(400)

    def perform(self, callback, identifier):
        database, conn = opendb()
        try:
            path = database.execute("SELECT path FROM books WHERE isbn = '{0}'".format(identifier)).fetchone()["path"]
        except TypeError:
            output = ""
            tornado.ioloop.IOLoop.instance().add_callback(lambda: callback("Nope."))
            raise tornado.web.HTTPError(404)
        finally:
            conn.close()

        output = EPUB(path).contents
        tornado.ioloop.IOLoop.instance().add_callback(lambda: callback(output))

    def on_callback(self, output):
        self.set_header("Content-Type", "application/json")
        self.write(json.JSONEncoder().encode(output))
        self.flush()
        self.finish()


class GetFilePart(tornado.web.RequestHandler):

    @tornado.web.asynchronous
    def get(self, identifier, part, section=False):
        if identifier and part and not section:
            try:
                self.thread = Thread(target=self.perform, args=(self.on_callback, identifier, part,))
                self.thread.start()
            except IOError:
                raise tornado.web.HTTPError(404)
        elif identifier and part and section:
            try:
                self.thread = Thread(target=self.perform, args=(self.on_callback, identifier, part, section,))
                self.thread.start()
            except IOError:
                raise tornado.web.HTTPError(404)
        else:
            raise tornado.web.HTTPError(405)

    def perform(self, callback, identifier, part, section=False):
        database, conn = opendb()
        try:
            path = database.execute("SELECT path FROM books WHERE isbn = '{0}'".format(identifier)).fetchone()["path"]
        except TypeError:
            output = ""
            tornado.ioloop.IOLoop.instance().add_callback(lambda: callback("Nope."))
            raise tornado.web.HTTPError(404)
        finally:
            conn.close()
        try:
            epub = EPUB(path)
            part_path = ""
            for i in epub.contents:
                if part in i.keys():
                    part_path = i[part]
            output = epub.read(re.sub(r"#(.*)", "", part_path))  # strip fragment id.

            output = re.sub(r'(href|src)="(.*?)"', '\g<1>="/getpath/{0}/\g<2>"'.format(identifier), output)
            output = re.sub(r"(href|src)='(.*?)'", '\g<1>="/getpath/{0}/\g<2>"'.format(identifier), output)

            if section:
                try:
                    root = ET.fromstring(output)
                    section = int(section) - 1
                    name = root.find(".//{http://www.w3.org/1999/xhtml}body")[section]
                    output = " ".join([t for t in list(name.itertext())])
                except:
                    output = "Nope."
                    tornado.ioloop.IOLoop.instance().add_callback(lambda: callback(output))
                    raise tornado.web.HTTPError(404)

        except KeyError:
            output = "Nope."
            tornado.ioloop.IOLoop.instance().add_callback(lambda: callback(output))
            raise tornado.web.HTTPError(404)

        tornado.ioloop.IOLoop.instance().add_callback(lambda: callback(output))

    def on_callback(self, output):
        self.set_header("Content-Type", "text/html")
        self.set_header("Charset","UTF-8")
        self.write(output)
        self.flush()
        self.finish()


class GetFilePath(tornado.web.RequestHandler):

    @tornado.web.asynchronous
    def get(self, identifier, part):
        if identifier and part:
            try:
                self.thread = Thread(target=self.perform, args=(self.on_callback, identifier, part,))
                self.thread.start()
            except IOError:
                raise tornado.web.HTTPError(404)
        else:
            raise tornado.web.HTTPError(400)

    def perform(self, callback, identifier, part):
        database, conn = opendb()
        try:
            path = database.execute("SELECT path FROM books WHERE isbn = '{0}'".format(identifier)).fetchone()["path"]
        except TypeError:
            output = ""
            tornado.ioloop.IOLoop.instance().add_callback(lambda: callback("Nope."))
            raise tornado.web.HTTPError(404)
        finally:
            conn.close()
        filepath = ""
        try:
            epub = EPUB(path)
            for i in epub.namelist():
                if i.endswith(part):
                    filepath = i
            output = epub.read(filepath)

        except KeyError:
            output = "Nope."
            pass

        finally:
            tornado.ioloop.IOLoop.instance().add_callback(lambda: callback(output))

    def on_callback(self, output):
        self.set_header("Content-Type", "text/html")
        self.write(output)
        self.flush()
        self.finish()


class DownloadPublication(tornado.web.RequestHandler):

    def get(self, filename):
        if filename:
            database, conn = opendb()
            try:
                path = database.execute("SELECT path FROM books WHERE isbn = '{0}' ".format(filename)).fetchone()["path"]
            except TypeError:
                raise tornado.web.HTTPError(404)
            finally:
                conn.close()
            output = open(path, "r")
            self.set_header('Content-Type', 'application/zip')
            self.set_header('Content-Disposition', 'attachment; filename='+os.path.basename(path)+'')
            self.write(output.read())
        else:
            raise tornado.web.HTTPError(404)


class OPDSCatalogue(tornado.web.RequestHandler):
    def get(self):
        catalogue = opds.generateCatalogRoot()
        self.set_header("Content-Type", "application/atom+xml")
        self.write(catalogue)

