#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'Michael Liao'

'''
Database operation module. This module is independent with web module.
'''

import time, logging

import db


class Field(object):    # 定义一个 Field 类
    _count = 0

    def __init__(self, **kw):
        self.name = kw.get('name', None)    # 从 kw 中获取 key 为 name 的 value，不存在则为 None
        self._default = kw.get('default', None)    # 从 kw 中获取 key 为 default 的 value，不存在则为 None
        self.primary_key = kw.get('primary_key', False)    # 从 kw 中获取 key 为 primary_key 的 value，不存在则为 None
        self.nullable = kw.get('nullable', False)    # 从 kw 中获取 key 为 null 的 value，不存在则为 None
        self.updatable = kw.get('updatable', True)    # 从 kw 中获取 key 为 updatable 的 value，不存在则为 None
        self.insertable = kw.get('insertable', True)    # 从 kw 中获取 key 为 insertable 的 value，不存在则为 None
        self.ddl = kw.get('ddl', '')    # 从 kw 中获取 key 为 ddl 的 value，不存在则为 None
        self._order = Field._count
        Field._count += 1

    @property
    def default(self):
        d = self._default
        return d() if callable(d) else d    # 如果 self._default 是一个 callable 对象，则 call 这个对象

    def __str__(self):
        s = ['<%s:%s,%s,default(%s),' % (self.__class__.__name__, self.name, self.ddl, self._default)]
        self.nullable and s.append('N')
        self.updatable and s.append('U')
        self.insertable and s.append('I')
        s.append('>')
        return ''.join(s)


class StringField(Field):    # StringField 类继承自 Field
    def __init__(self, **kw):
        if not 'default' in kw:    # 从 kw 中获取 key 为 default 的值， 若不存在则 default 为 ""
            kw['default'] = ''
        if not 'ddl' in kw:    # 从 kw 中获取 key 为 ddl 的值，若不存在则为 varchar(255)
            kw['ddl'] = 'varchar(255)'
        super(StringField, self).__init__(**kw)


class IntegerField(Field):    # IntegerField 类继承自 Field
    def __init__(self, **kw):
        if not 'default' in kw:    # 从 kw 中获取 key 为 default 的值， 若不存在则 default 为 0
            kw['default'] = 0
        if not 'ddl' in kw:    # 从 kw 中获取 key 为 ddl 的值，若不存在则为 bigint
            kw['ddl'] = 'bigint'
        super(IntegerField, self).__init__(**kw)


class FloatField(Field):    # FloatField 类继承自 Field
    def __init__(self, **kw):
        if not 'default' in kw:    # 从 kw 中获取 key 为 default 的值， 若不存在则 default 为 0.0
            kw['default'] = 0.0
        if not 'ddl' in kw:    # 从 kw 中获取 key 为 ddl 的值，若不存在则为 real
            kw['ddl'] = 'real'
        super(FloatField, self).__init__(**kw)


class BooleanField(Field):   # BooleanField 类继承自 Field
    def __init__(self, **kw):
        if not 'default' in kw:    # 从 kw 中获取 key 为 default 的值， 若不存在则 default 为 False
            kw['default'] = False
        if not 'ddl' in kw:    # 从 kw 中获取 key 为 ddl 的值，若不存在则为 bool
            kw['ddl'] = 'bool'
        super(BooleanField, self).__init__(**kw)


class TextField(Field):    # TextField 类继承自 Field
    def __init__(self, **kw):
        if not 'default' in kw:    # 从 kw 中获取 key 为 default 的值， 若不存在则 default 为 ""
            kw['default'] = ''
        if not 'ddl' in kw:
            kw['ddl'] = 'text'    # 从 kw 中获取 key 为 ddl 的值，若不存在则为 text
        super(TextField, self).__init__(**kw)


class BlobField(Field):    # BlobField 类继承自 Field
    def __init__(self, **kw):
        if not 'default' in kw:    # 从 kw 中获取 key 为 default 的值， 若不存在则 default 为 ""
            kw['default'] = ''
        if not 'ddl' in kw:
            kw['ddl'] = 'blob'    # 从 kw 中获取 key 为 ddl 的值，若不存在则为 blob
        super(BlobField, self).__init__(**kw)


class VersionField(Field):    # VersionField 类继承自 Field
    def __init__(self, name=None):
        super(VersionField, self).__init__(name=name, default=0, ddl='bigint')


_triggers = frozenset(['pre_insert', 'pre_update', 'pre_delete'])


def _gen_sql(table_name, mappings):    # 生成 sql 语句函数
    pk = None
    sql = ['-- generating SQL for %s:' % table_name, 'create table `%s` (' % table_name]
    for f in sorted(mappings.values(), lambda x, y: cmp(x._order, y._order)):
        if not hasattr(f, 'ddl'):
            raise StandardError('no ddl in field "%s".' % n)
        ddl = f.ddl
        nullable = f.nullable
        if f.primary_key:
            pk = f.name
        sql.append(nullable and '  `%s` %s,' % (f.name, ddl) or '  `%s` %s not null,' % (f.name, ddl))
    sql.append('  primary key(`%s`)' % pk)
    sql.append(');')
    return '\n'.join(sql)


class ModelMetaclass(type):   # model 类的元类
    '''
    Metaclass for model objects.
    '''

    def __new__(cls, name, bases, attrs):
        # skip base Model class:
        if name == 'Model':    # 如果类名为 model， 则创建这个类
            return type.__new__(cls, name, bases, attrs)

        # store all subclasses info:
        if not hasattr(cls, 'subclasses'):
            cls.subclasses = {}
        if not name in cls.subclasses:
            cls.subclasses[name] = name
        else:
            logging.warning('Redefine class: %s' % name)

        logging.info('Scan ORMapping %s...' % name)
        mappings = dict()    # 初始化 mappings 为一个空字典，用于保存映射关系
        primary_key = None    # 初始化 primary_key 为 None, 用于在后续循环中检查是否定义多个 primary_key
        for k, v in attrs.iteritems():    # 遍历这个类的所有 attr
            if isinstance(v, Field):    # 如果 v 为 Field 类的实例
                if not v.name:   # 如果 v.name 不存在
                    v.name = k   # 则将 k 的值赋给 v.name
                logging.info('Found mapping: %s => %s' % (k, v))
                # check duplicate primary key:
                if v.primary_key:    # 如果 v 有 primary_key 属性
                    if primary_key:    # 如果 primary_key 存在则定义了多个 primary_key
                        raise TypeError('Cannot define more than 1 primary key in class: %s' % name)
                    if v.updatable:    # 如果 primary_key 为 updatable = True 则修改 updatable = False
                        logging.warning('NOTE: change primary key to non-updatable.')
                        v.updatable = False
                    if v.nullable:    # 如果 primary_key 为 nullable = True 则修改 nullable = False
                        logging.warning('NOTE: change primary key to non-nullable.')
                        v.nullable = False
                    primary_key = v    # 将 v 赋值给 primary_key
                mappings[k] = v    # 将 k 和 v 存入 mappings
        # check exist of primary key:
        if not primary_key:    # 如果 primary_key
            raise TypeError('Primary key not defined in class: %s' % name)
        for k in mappings.iterkeys():    # 将 mapping 中的 k 从 attr 中 pop
            attrs.pop(k)
        if not '__table__' in attrs:    # 如果 __table__ 不存在与 attrs 中
            attrs['__table__'] = name.lower()   # 则将 attr['__table__'] 赋值为 name.lower()
        attrs['__mappings__'] = mappings  # 将 attr['__mappings__'] 赋值为 mappings
        attrs['__primary_key__'] = primary_key    # 将 attr['__primary_key__'] 赋值为 primary_key
        attrs['__sql__'] = lambda self: _gen_sql(attrs['__table__'], mappings)  # attrs['__sql__'] 赋值为 _gen_sql
        for trigger in _triggers:    # 如果 attrs 中不包括 _triggers 中的任意一项，则 attrs['trigger'] 为 None
            if not trigger in attrs:
                attrs[trigger] = None
        return type.__new__(cls, name, bases, attrs)    # 在上述操作都执行完成之后，创建类


class Model(dict):    # Model 类
    '''
    Base class for ORM.

    >>> class User(Model):
    ...     id = IntegerField(primary_key=True)
    ...     name = StringField()
    ...     email = StringField(updatable=False)
    ...     passwd = StringField(default=lambda: '******')
    ...     last_modified = FloatField()
    ...     def pre_insert(self):
    ...         self.last_modified = time.time()
    >>> u = User(id=10190, name='Michael', email='orm@db.org')
    >>> r = u.insert()
    >>> u.email
    'orm@db.org'
    >>> u.passwd
    '******'
    >>> u.last_modified > (time.time() - 2)
    True
    >>> f = User.get(10190)
    >>> f.name
    u'Michael'
    >>> f.email
    u'orm@db.org'
    >>> f.email = 'changed@db.org'
    >>> r = f.update() # change email but email is non-updatable!
    >>> len(User.find_all())
    1
    >>> g = User.get(10190)
    >>> g.email
    u'orm@db.org'
    >>> r = g.delete()
    >>> len(db.select('select * from user where id=10190'))
    0
    >>> import json
    >>> print User().__sql__()
    -- generating SQL for user:
    create table `user` (
      `id` bigint not null,
      `name` varchar(255) not null,
      `email` varchar(255) not null,
      `passwd` varchar(255) not null,
      `last_modified` real not null,
      primary key(`id`)
    );
    '''
    __metaclass__ = ModelMetaclass    # 指定 metaclass 为 ModelMetaclass

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):    # 重载 __getattr__ 方法，使得 Model 类支持 object.key 方式获取 value
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Dict' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):    # 重载 __setattr__ 方法，使得 Dict 支持 object.key = value 方式赋值
        self[key] = value

    @classmethod
    def get(cls, pk):
        '''
        Get by primary key.
        '''
        d = db.select_one('select * from %s where %s=?' % (cls.__table__, cls.__primary_key__.name), pk)
        return cls(**d) if d else None    # 若 d 存在则返回实例化 d 并返回

    @classmethod
    def find_first(cls, where, *args):
        '''
        Find by where clause and return one result. If multiple results found, 
        only the first one returned. If no result found, return None.
        '''
        d = db.select_one('select * from %s %s' % (cls.__table__, where), *args)
        return cls(**d) if d else None

    @classmethod
    def find_all(cls, *args):
        '''
        Find all and return list.
        '''
        L = db.select('select * from `%s`' % cls.__table__)
        return [cls(**d) for d in L]

    @classmethod
    def find_by(cls, where, *args):
        '''
        Find by where clause and return list.
        '''
        L = db.select('select * from `%s` %s' % (cls.__table__, where), *args)
        return [cls(**d) for d in L]

    @classmethod
    def count_all(cls):
        '''
        Find by 'select count(pk) from table' and return integer.
        '''
        return db.select_int('select count(`%s`) from `%s`' % (cls.__primary_key__.name, cls.__table__))

    @classmethod
    def count_by(cls, where, *args):
        '''
        Find by 'select count(pk) from table where ... ' and return int.
        '''
        return db.select_int('select count(`%s`) from `%s` %s' % (cls.__primary_key__.name, cls.__table__, where),
                             *args)

    def update(self):    # 通过主键来更新一条记录
        self.pre_update and self.pre_update()   # 如果 self.pre_update 不为空则执行 self.pre_update
        L = []
        args = []
        for k, v in self.__mappings__.iteritems():  # 依次迭代 __mappings__ 中所有 key 和 value
            if v.updatable:    # 如果 v.updatable
                if hasattr(self, k):  # 如果实例有名为 k 的属性
                    arg = getattr(self, k)  # 获取 k 属性对应的值，并赋值给 args
                else:    # 如果无名为 k 的属性
                    arg = v.default    # 获取 k 属性对应的默认值，并赋值给 args
                    setattr(self, k, arg)    # 将实例 k 属性的赋值为 args
                L.append('`%s`=?' % k)
                args.append(arg)
        pk = self.__primary_key__.name
        args.append(getattr(self, pk))
        db.update('update `%s` set %s where %s=?' % (self.__table__, ','.join(L), pk), *args)
        return self

    def delete(self):    # 通过主键来删除一条记录
        self.pre_delete and self.pre_delete()
        pk = self.__primary_key__.name
        args = (getattr(self, pk),)
        db.update('delete from `%s` where `%s`=?' % (self.__table__, pk), *args)
        return self

    def insert(self):    # 通过主键来插入一条记录
        self.pre_insert and self.pre_insert()
        params = {}
        for k, v in self.__mappings__.iteritems():
            if v.insertable:
                if not hasattr(self, k):
                    setattr(self, k, v.default)
                params[v.name] = getattr(self, k)
        db.insert('%s' % self.__table__, **params)
        return self


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    db.create_engine('www-data', 'www-data', 'test')
    db.update('drop table if exists user')
    db.update('create table user (id int primary key, name text, email text, passwd text, last_modified real)')
    import doctest

    doctest.testmod()
