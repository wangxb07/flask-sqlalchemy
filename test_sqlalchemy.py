from __future__ import with_statement

import os
import atexit
import unittest
from datetime import datetime
import flask
from flaskext import sqlalchemy


def make_todo_model(db):
    class Todo(db.Model):
        __tablename__ = 'todos'
        id = db.Column('todo_id', db.Integer, primary_key=True)
        title = db.Column(db.String(60))
        text = db.Column(db.String)
        done = db.Column(db.Boolean)
        pub_date = db.Column(db.DateTime)

        def __init__(self, title, text):
            self.title = title
            self.text = text
            self.done = False
            self.pub_date = datetime.utcnow()
    return Todo


class BasicAppTestCase(unittest.TestCase):

    def setUp(self):
        app = flask.Flask(__name__)
        app.config['SQLALCHEMY_ENGINE'] = 'sqlite://'
        app.config['TESTING'] = True
        db = sqlalchemy.SQLAlchemy(app)
        self.Todo = make_todo_model(db)

        @app.route('/')
        def index():
            return '\n'.join(x.title for x in self.Todo.query.all())

        @app.route('/add', methods=['POST'])
        def add():
            form = flask.request.form
            todo = self.Todo(form['title'], form['text'])
            db.session.add(todo)
            db.session.commit()
            return 'added'

        db.create_all()

        self.app = app
        self.db = db

    def tearDown(self):
        self.db.drop_all()

    def test_basic_insert(self):
        c = self.app.test_client()
        c.post('/add', data=dict(title='First Item', text='The text'))
        c.post('/add', data=dict(title='2nd Item', text='The text'))
        rv = c.get('/')
        assert rv.data == 'First Item\n2nd Item'

    def test_query_recording(self):
        with self.app.test_request_context():
            todo = self.Todo('Test 1', 'test')
            self.db.session.add(todo)
            self.db.session.commit()

            queries = sqlalchemy.get_debug_queries()
            self.assertEqual(len(queries), 1)
            query = queries[0]
            self.assert_('insert into' in query.statement.lower())
            self.assertEqual(query.parameters[0], 'Test 1')
            self.assertEqual(query.parameters[1], 'test')
            self.assert_('test_sqlalchemy.py' in query.context)
            self.assert_('test_query_recording' in query.context)

    def test_helper_api(self):
        self.assertEqual(self.db.metadata, self.db.Model.metadata)


class TestQueryProperty(unittest.TestCase):

    def setUp(self):
        self.app = flask.Flask(__name__)
        self.app.config['SQLALCHEMY_ENGINE'] = 'sqlite://'
        self.app.config['TESTING'] = True

    def test_no_app_bound(self):
        db = sqlalchemy.SQLAlchemy()
        db.init_app(self.app)
        Todo = make_todo_model(db)

        # If no app is bound to the SQLAlchemy instance, a
        # request context is required to access Model.query.
        self.assertRaises(RuntimeError, getattr, Todo, 'query')
        with self.app.test_request_context():
            db.create_all()
            todo = Todo('Test', 'test')
            db.session.add(todo)
            db.session.commit()
            self.assertEqual(len(Todo.query.all()), 1)

    def test_app_bound(self):
        db = sqlalchemy.SQLAlchemy(self.app)
        Todo = make_todo_model(db)
        db.create_all()

        # If an app was passed to the SQLAlchemy constructor,
        # the query property is always available.
        todo = Todo('Test', 'test')
        db.session.add(todo)
        db.session.commit()
        self.assertEqual(len(Todo.query.all()), 1)


class SignallingTestCase(unittest.TestCase):

    def setUp(self):
        self.app = app = flask.Flask(__name__)
        app.config['SQLALCHEMY_ENGINE'] = 'sqlite://'
        app.config['TESTING'] = True
        self.db = sqlalchemy.SQLAlchemy(app)
        self.Todo = make_todo_model(self.db)
        self.db.create_all()

    def tearDown(self):
        self.db.drop_all()

    def test_model_signals(self):
        recorded = []
        def committed(sender, changes):
            self.assert_(isinstance(changes, list))
            recorded.extend(changes)
        with sqlalchemy.models_committed.connected_to(committed,
                                                      sender=self.app):
            todo = self.Todo('Awesome', 'the text')
            self.db.session.add(todo)
            self.assertEqual(len(recorded), 0)
            self.db.session.commit()
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0][0], todo)
            self.assertEqual(recorded[0][1], 'insert')
            del recorded[:]
            todo.text = 'aha'
            self.db.session.commit()
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0][0], todo)
            self.assertEqual(recorded[0][1], 'update')
            del recorded[:]
            self.db.session.delete(todo)
            self.db.session.commit()
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0][0], todo)
            self.assertEqual(recorded[0][1], 'delete')


class HelperTestCase(unittest.TestCase):

    def test_default_table_name(self):
        app = flask.Flask(__name__)
        app.config['SQLALCHEMY_ENGINE'] = 'sqlite://'
        db = sqlalchemy.SQLAlchemy(app)

        class FOOBar(db.Model):
            id = db.Column(db.Integer, primary_key=True)
        class BazBar(db.Model):
            id = db.Column(db.Integer, primary_key=True)

        self.assertEqual(FOOBar.__tablename__, 'foo_bar')
        self.assertEqual(BazBar.__tablename__, 'baz_bar')


class PaginationTestCase(unittest.TestCase):

    def test_basic_pagination(self):
        p = sqlalchemy.Pagination(None, 1, 20, 500, [])
        self.assertEqual(p.page, 1)
        self.assertFalse(p.has_prev)
        self.assert_(p.has_next)
        self.assertEqual(p.total, 500)
        self.assertEqual(p.pages, 25)
        self.assertEqual(p.next_num, 2)
        self.assertEqual(list(p.iter_pages()),
                         [1, 2, 3, 4, 5, None, 24, 25])
        p.page = 10
        self.assertEqual(list(p.iter_pages()),
                         [1, 2, None, 8, 9, 10, 11, 12, 13, 14, None, 24, 25])


class BindsTestCase(unittest.TestCase):

    def test_basic_binds(self):
        import tempfile
        _, db1 = tempfile.mkstemp()
        _, db2 = tempfile.mkstemp()
        def _remove_files():
            try:
                os.remove(db1)
                os.remove(db2)
            except IOError:
                pass
        atexit.register(_remove_files)

        app = flask.Flask(__name__)
        app.config['SQLALCHEMY_ENGINE'] = 'sqlite://'
        app.config['SQLALCHEMY_BINDS'] = {
            'foo':      'sqlite:///' + db1,
            'bar':      'sqlite:///' + db2
        }
        db = sqlalchemy.SQLAlchemy(app)

        class Foo(db.Model):
            __bind_key__ = 'foo'
            __table_args__ = {"info": {"bind_key": "foo"}}
            id = db.Column(db.Integer, primary_key=True)

        class Bar(db.Model):
            __bind_key__ = 'bar'
            id = db.Column(db.Integer, primary_key=True)

        class Baz(db.Model):
            id = db.Column(db.Integer, primary_key=True)

        db.create_all()

        # simple way to check if the engines are looked up properly
        self.assertEqual(db.get_engine(app, None), db.engine)
        for key in 'foo', 'bar':
            engine = db.get_engine(app, key)
            connector = app.extensions['sqlalchemy'].connectors[key]
            self.assertEqual(engine, connector.get_engine())
            self.assertEqual(str(engine.url),
                             app.config['SQLALCHEMY_BINDS'][key])

        # do the models have the correct engines?
        self.assertEqual(db.metadata.tables['foo'].info['bind_key'], 'foo')
        self.assertEqual(db.metadata.tables['bar'].info['bind_key'], 'bar')
        self.assertEqual(db.metadata.tables['baz'].info.get('bind_key'), None)

        # see the tables created in an engine
        metadata = db.MetaData()
        metadata.reflect(bind=db.get_engine(app, 'foo'))
        self.assertEqual(len(metadata.tables), 1)
        self.assert_('foo' in metadata.tables)

        metadata = db.MetaData()
        metadata.reflect(bind=db.get_engine(app, 'bar'))
        self.assertEqual(len(metadata.tables), 1)
        self.assert_('bar' in metadata.tables)

        metadata = db.MetaData()
        metadata.reflect(bind=db.get_engine(app))
        self.assertEqual(len(metadata.tables), 1)
        self.assert_('baz' in metadata.tables)

        # do the session have the right binds set?
        self.assertEqual(db.get_binds(app), {
            Foo.__table__: db.get_engine(app, 'foo'),
            Bar.__table__: db.get_engine(app, 'bar'),
            Baz.__table__: db.get_engine(app, None)
        })


class DefaultQueryClassTestCase(unittest.TestCase):

    def test_default_query_class(self):
        app = flask.Flask(__name__)
        app.config['SQLALCHEMY_ENGINE'] = 'sqlite://'
        app.config['TESTING'] = True
        db = sqlalchemy.SQLAlchemy(app)

        class Parent(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            children = db.relationship("Child", backref = db.backref("parents", lazy='dynamic'), lazy='dynamic')
        class Child(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            parent_id = db.Column(db.Integer, db.ForeignKey('parent.id'))
        p = Parent()
        c = Child()
        c.parent = p
        self.assertEqual(type(Parent.query), sqlalchemy.BaseQuery)
        self.assertEqual(type(Child.query), sqlalchemy.BaseQuery)
        self.assert_(isinstance(p.children, sqlalchemy.BaseQuery))
        self.assert_(isinstance(c.parents, sqlalchemy.BaseQuery))


class SQLAlchemyIncludesTestCase(unittest.TestCase):

    def test(self):
        """Various SQLAlchemy objects are exposed as attributes.
        """
        db = sqlalchemy.SQLAlchemy()

        import sqlalchemy as sqlalchemy_lib
        self.assertTrue(db.Column == sqlalchemy_lib.Column)

        # The Query object we expose is actually our own subclass.
        from flaskext.sqlalchemy import BaseQuery
        self.assertTrue(db.Query == BaseQuery)


class RegressionTestCase(unittest.TestCase):

    def test_joined_inheritance(self):
        app = flask.Flask(__name__)
        db = sqlalchemy.SQLAlchemy(app)

        class Base(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            type = db.Column(db.Unicode(20))
            __mapper_args__ = {'polymorphic_on': type}

        class SubBase(Base):
            id = db.Column(db.Integer, db.ForeignKey('base.id'),
                           primary_key=True)
            __mapper_args__ = {'polymorphic_identity': 'sub'}

        self.assertEqual(Base.__tablename__, 'base')
        self.assertEqual(SubBase.__tablename__, 'sub_base')
        db.create_all()

    def test_single_table_inheritance(self):
        app = flask.Flask(__name__)
        db = sqlalchemy.SQLAlchemy(app)

        class Base(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            type = db.Column(db.Unicode(20))
            __mapper_args__ = {'polymorphic_on': type}

        class SubBase(Base):
            __mapper_args__ = {'polymorphic_identity': 'sub'}

        self.assertEqual(Base.__tablename__, 'base')
        self.assertEqual(SubBase.__tablename__, 'base')
        db.create_all()

    def test_joined_inheritance_relation(self):
        app = flask.Flask(__name__)
        db = sqlalchemy.SQLAlchemy(app)

        class Relation(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            base_id = db.Column(db.Integer, db.ForeignKey('base.id'))
            name = db.Column(db.Unicode(20))

            def __init__(self, name):
                self.name = name

        class Base(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            type = db.Column(db.Unicode(20))
            __mapper_args__ = {'polymorphic_on': type}

        class SubBase(Base):
            id = db.Column(db.Integer, db.ForeignKey('base.id'),
                           primary_key=True)
            __mapper_args__ = {'polymorphic_identity': u'sub'}
            relations = db.relationship(Relation)

        db.create_all()

        base = SubBase()
        base.relations = [Relation(name=u'foo')]
        db.session.add(base)
        db.session.commit()

        base = base.query.one()

    def test_connection_binds(self):
        app = flask.Flask(__name__)
        db = sqlalchemy.SQLAlchemy(app)
        assert db.session.connection()


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(BasicAppTestCase))
    suite.addTest(unittest.makeSuite(TestQueryProperty))
    suite.addTest(unittest.makeSuite(HelperTestCase))
    suite.addTest(unittest.makeSuite(PaginationTestCase))
    suite.addTest(unittest.makeSuite(BindsTestCase))
    suite.addTest(unittest.makeSuite(DefaultQueryClassTestCase))
    suite.addTest(unittest.makeSuite(SQLAlchemyIncludesTestCase))
    suite.addTest(unittest.makeSuite(RegressionTestCase))
    if flask.signals_available:
        suite.addTest(unittest.makeSuite(SignallingTestCase))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
