# -*- coding: utf-8 -*-
"""
    werkzeug.local
    ~~~~~~~~~~~~~~

    This module implements context-local objects.

    :copyright: (c) 2010 by the Werkzeug Team, see AUTHORS for more details.
    :license: BSD, see LICENSE for more details.
"""
try:
    from greenlet import getcurrent as get_current_greenlet
except ImportError: # pragma: no cover
    try:
        from py.magic import greenlet
        get_current_greenlet = greenlet.getcurrent
        del greenlet
    except:
        # catch all, py.* fails with so many different errors.
        get_current_greenlet = int
try:
    from thread import get_ident as get_current_thread, allocate_lock
except ImportError: # pragma: no cover
    from dummy_thread import get_ident as get_current_thread, allocate_lock

from werkzeug.wsgi import ClosingIterator
from werkzeug._internal import _patch_wrapper


# get the best ident function.  if greenlets are not installed we can
# safely just use the builtin thread function and save a python methodcall
# and the cost of calculating a hash.
if get_current_greenlet is int: # pragma: no cover
    get_ident = get_current_thread
else:
    get_ident = lambda: (get_current_thread(), get_current_greenlet())


def release_local(local):
    """Releases the contents of the local for the current context.
    This makes it possible to use locals without a manager.

    Example::

        >>> loc = Local()
        >>> loc.foo = 42
        >>> release_local(loc)
        >>> hasattr(loc, 'foo')
        False

    With this function one can release :class:`Local` objects as well
    as :class:`StackLocal` objects.  However it is not possible to
    release data held by proxies that way, one always has to retain
    a reference to the underlying local object in order to be able
    to release it.

    .. versionadded:: 0.6.1
    """
    local.__release_local__()    # 传递一个实例化的 local 类， 并执行 __release_local__ 方法


class Local(object):    # Local 对象
    __slots__ = ('__storage__', '__lock__')    # 定义slots， 只允许动态添加 __storage__ 和 __lock__ 属性

    def __init__(self):     # 初始化方法，会新增两个属性 __storage__ 和 __lock__，值分别为 {} 和 allocate_lock()
        object.__setattr__(self, '__storage__', {})
        object.__setattr__(self, '__lock__', allocate_lock())

    # __storage__ 是一个嵌套字典，形式如下：{“线程1或协程1的 id“:{"key1":"value1", "key2":"value2"}, “线程2或协程2的 id“:{"key1":"value1", "key2":"value2"}......}
    # 通过此方式， 实现线程或协程的数据访问隔离

    """
    example1:

    from werkzeug import Local

    a = Local()

    a.message = "this is a message"

    a.__storage__

    output: {<greenlet.greenlet at 0x7feb568675f0>: {'message': 'this is a message'}}

    example2:

    m = a("message")

    m

    output: 'this is a message'
    """

    def __iter__(self):
        return self.__storage__.iteritems()

    def __call__(self, proxy):    # __call__ 方法需要传入一个参数，参数为对象属性名，返回一个 LocalProxy 对象
        """Create a proxy for a name."""
        return LocalProxy(self, proxy)

    def __release_local__(self):    # release 操作，从 __storage__ 中 pop 对应线程或协程的所有数据
        self.__storage__.pop(get_ident(), None)

    def __getattr__(self, name):    # 重载 __getattr__ 方法，在获取属性时，先获取此线程或协程的 id， 在通过 id 和 key 获取对应的 value
        self.__lock__.acquire()    # 先获取锁
        try:
            try:
                return self.__storage__[get_ident()][name]
            except KeyError:
                raise AttributeError(name)
        finally:
            self.__lock__.release() # 释放锁

    def __setattr__(self, name, value):  # 重载 __getattr__ 方法，在给属性赋值时，先获取此线程或协程的 id， 在通过 id 将 key 的值赋值为 value
        self.__lock__.acquire() # 先获取锁
        try:
            ident = get_ident()
            storage = self.__storage__
            if ident in storage:
                storage[ident][name] = value    # 如果线程或协程的 id 对应的字典存在，则修改对应 key 的 value
            else:
                storage[ident] = {name: value}     # 如果线程或协程的 id 对应的不字典存在，则赋值 {key: value}
        finally:
            self.__lock__.release() # 释放锁

    def __delattr__(self, name): # 重载 __delattr__ 方法，在删除属性时，先获取此线程或协程的 id， 在通过 id 删除对应 key 和 value
        self.__lock__.acquire() # 先获取锁
        try:
            try:
                del self.__storage__[get_ident()][name]
            except KeyError:
                raise AttributeError(name)
        finally:
            self.__lock__.release() # 释放锁


class LocalStack(object):    # LocalStack 对象
    """This class works similar to a :class:`Local` but keeps a stack
    of objects instead.  This is best explained with an example::

        >>> ls = LocalStack()
        >>> ls.push(42)
        >>> ls.top
        42
        >>> ls.push(23)
        >>> ls.top
        23
        >>> ls.pop()
        23
        >>> ls.top
        42

    They can be force released by using a :class:`LocalManager` or with
    the :func:`release_local` function but the correct way is to pop the
    item from the stack after using.  When the stack is empty it will
    no longer be bound to the current context (and as such released).

    By calling the stack without arguments it returns a proxy that resolves to
    the topmost item on the stack.

    .. versionadded:: 0.6.1
    """

    def __init__(self):
        self._local = Local()    # _local 属性是实例化的 Local 对象
        self._lock = allocate_lock()

    # LocalStack 中所有的数据操作都是基于 self.local 即实例化的 Local 对象完成的
    # self._local 的 __storage__ 结构： {“线程1或协程1的 id“:{"stack": [obj1, obj2], "key1":"value1", "key2":"value2"}, “线程2或协程2的 id“:{"stack": [obj1, obj2],"key1":"value1", "key2":"value2"}......}
    # 通过此方式，用 list 实现了一个 stack， 并且实现线程或协程的数据访问隔离

    """
    example1:

    a = LocalStack()

    a.push(2)

    a.__dict__
    output: {'_local': <werkzeug.local.Local at 0x7feb568392d0>}

    a._local.__storage__
    output: {<greenlet.greenlet at 0x7feb568675f0>: {'stack': [2]}}

    example2:

    class test(object):
        pass

    t = test()

    t.a = 1

    t.b = 2

    l = LocalStack()

    l.push(t)

    lpa = LocalProxy(lambda: t.a)

    lpa

    output: 1

    """

    def __release_local__(self):
        self._local.__release_local__()

    def __call__(self):  # 重载 __call__ 方法
        def _lookup():  # 定义一个 _lookup 方法， 通过 self.top 方法判断 stack 中是否有对象
            rv = self.top   # 执行 self.top 操作
            if rv is None:    # 如果 rv 为空则跑出异常
                raise RuntimeError('object unbound')
            return rv  # 返回 rv
        return LocalProxy(_lookup)

    def push(self, obj):    # push 操作， 即入栈操作
        """Pushes a new item to the stack"""
        self._lock.acquire()    # 先获取锁
        try:
            rv = getattr(self._local, 'stack', None)    # 获取 self._local 即实例化的 Local 对象的 stack 属性
            if rv is None:  # 如果属性不存在
                self._local.stack = rv = []   # 初始化 self._local 即实例化的 Local 对象的 stack 为 []
            rv.append(obj)    # 并将 obj append 到列表中
            return rv
        finally:
            self._lock.release() # 释放锁

    def pop(self):    # pop 操作，即出栈操作
        """Removes the topmost item from the stack, will return the
        old value or `None` if the stack was already empty.
        """
        self._lock.acquire() # 先获取锁
        try:
            stack = getattr(self._local, 'stack', None)    # 获取 self._local 即实例化的 Local 对象的 stack 属性
            if stack is None:    # 如果属性不存在
                return None
            elif len(stack) == 1:    # 如果 stack 内的元素为一个
                release_local(self._local)     # 执行 release_local 操作
                return stack[-1]     # 并返回 stack 中的元素
            else:
                return stack.pop()    # pop stack 中最后一个
        finally:
            self._lock.release()    # 释放锁

    @property
    def top(self):    #  top 方法可以通过 self.top 方式调用
        """The topmost item on the stack.  If the stack is empty,
        `None` is returned.
        """
        try:
            return self._local.stack[-1]    # 返回 stack 中最后一个对象
        except (AttributeError, IndexError):
            return None


class LocalManager(object):    # LocalManager 对象
    """Local objects cannot manage themselves. For that you need a local
    manager.  You can pass a local manager multiple locals or add them later
    by appending them to `manager.locals`.  Everytime the manager cleans up
    it, will clean up all the data left in the locals for this context.

    .. versionchanged:: 0.6.1
       Instead of a manager the :func:`release_local` function can be used
       as well.
    """

    def __init__(self, locals=None):
        if locals is None:    # 如果 locals 为空
            self.locals = []    # 则 self.locals = []
        elif isinstance(locals, Local):    # 如果 locals 为 Local 类的实例
            self.locals = [locals]    # 则 self.locals = [locals]
        else:
            self.locals = list(locals)  # self.locals = [locals]

    def get_ident(self):    # 获取当前线程或协程的 id
        """Return the context identifier the local objects use internally for
        this context.  You cannot override this method to change the behavior
        but use it to link other context local objects (such as SQLAlchemy's
        scoped sessions) to the Werkzeug locals.
        """
        return get_ident()

    def cleanup(self):
        """Manually clean up the data in the locals for this context.  Call
        this at the end of the request or use `make_middleware()`.
        """
        ident = self.get_ident()    # 获取当前线程或协程的 id
        for local in self.locals:    # 依次迭代所有 self.locals 中的对象， 执行 release_local 方法
            release_local(local)

    def make_middleware(self, app):
        """Wrap a WSGI application so that cleaning up happens after
        request end.
        """
        def application(environ, start_response):
            return ClosingIterator(app(environ, start_response), self.cleanup)
        return application

    def middleware(self, func):
        """Like `make_middleware` but for decorating functions.

        Example usage::

            @manager.middleware
            def application(environ, start_response):
                ...

        The difference to `make_middleware` is that the function passed
        will have all the arguments copied from the inner application
        (name, docstring, module).
        """
        return _patch_wrapper(func, self.make_middleware(func))

    def __repr__(self):
        return '<%s storages: %d>' % (
            self.__class__.__name__,
            len(self.locals)
        )


class LocalProxy(object):    # LocalProxy 类
    """Acts as a proxy for a werkzeug local.  Forwards all operations to
    a proxied object.  The only operations not supported for forwarding
    are right handed operands and any kind of assignment.

    Example usage::

        from werkzeug import Local
        l = Local()

        # these are proxies
        request = l('request')
        user = l('user')


        from werkzeug import LocalStack
        _response_local = LocalStack()

        # this is a proxy
        response = _response_local()

    Whenever something is bound to l.user / l.request the proxy objects
    will forward all operations.  If no object is bound a :exc:`RuntimeError`
    will be raised.

    To create proxies to :class:`Local` or :class:`LocalStack` objects,
    call the object as shown above.  If you want to have a proxy to an
    object looked up by a function, you can (as of Werkzeug 0.6.1) pass
    a function to the :class:`LocalProxy` constructor::

        session = LocalProxy(lambda: get_current_request().session)

    .. versionchanged:: 0.6.1
       The class can be instanciated with a callable as well now.
    """
    __slots__ = ('__local', '__dict__', '__name__')    # 定义slots， 只允许动态添加 __local__, __dict__ 和 __name__ 属性

    def __init__(self, local, name=None):    # 定义两个属性 _LocalProxy__local 和 __name__， 值分别为 local， name
        object.__setattr__(self, '_LocalProxy__local', local)
        object.__setattr__(self, '__name__', name)

    def _get_current_object(self):    # 定义 _get _current_object 方法
        """Return the current object.  This is useful if you want the real
        object behind the proxy at a time for performance reasons or because
        you want to pass the object into a different context.
        """
        if not hasattr(self.__local, '__release_local__'):    # 如果 self.__local 无 __release_local__ 属性，则 self.__local 不是 Local 或 LocalStack 对象
            return self.__local()     # 调用 self.__local 的 __call__ 方法，并返回
        try:
            return getattr(self.__local, self.__name__)    # 返回 self.__local 的 self.__name__ 的值
        except AttributeError:
            raise RuntimeError('no object bound to %s' % self.__name__)

    """
    example1:

    from werkzeug import Local

    from werkzeug import LocalStack

    from werkzeug import LocalProxy

    a = Local()

    a.message = "this is a message"

    lpa = LocalProxy(a, 'message')

    lpa

    output: 'this is a message'


    """

    @property
    def __dict__(self):
        try:
            return self._get_current_object().__dict__
        except RuntimeError:
            return AttributeError('__dict__')

    def __repr__(self):
        try:
            obj = self._get_current_object()
        except RuntimeError:
            return '<%s unbound>' % self.__class__.__name__
        return repr(obj)

    def __nonzero__(self):
        try:
            return bool(self._get_current_object())
        except RuntimeError:
            return False

    def __unicode__(self):
        try:
            return unicode(self._get_current_object())
        except RuntimeError:
            return repr(self)

    def __dir__(self):
        try:
            return dir(self._get_current_object())
        except RuntimeError:
            return []

    def __getattr__(self, name):
        if name == '__members__':
            return dir(self._get_current_object())
        return getattr(self._get_current_object(), name)

    def __setitem__(self, key, value):
        self._get_current_object()[key] = value

    def __delitem__(self, key):
        del self._get_current_object()[key]

    def __setslice__(self, i, j, seq):
        self._get_current_object()[i:j] = seq

    def __delslice__(self, i, j):
        del self._get_current_object()[i:j]

    __setattr__ = lambda x, n, v: setattr(x._get_current_object(), n, v)
    __delattr__ = lambda x, n: delattr(x._get_current_object(), n)
    __str__ = lambda x: str(x._get_current_object())
    __lt__ = lambda x, o: x._get_current_object() < o
    __le__ = lambda x, o: x._get_current_object() <= o
    __eq__ = lambda x, o: x._get_current_object() == o
    __ne__ = lambda x, o: x._get_current_object() != o
    __gt__ = lambda x, o: x._get_current_object() > o
    __ge__ = lambda x, o: x._get_current_object() >= o
    __cmp__ = lambda x, o: cmp(x._get_current_object(), o)
    __hash__ = lambda x: hash(x._get_current_object())
    __call__ = lambda x, *a, **kw: x._get_current_object()(*a, **kw)
    __len__ = lambda x: len(x._get_current_object())
    __getitem__ = lambda x, i: x._get_current_object()[i]
    __iter__ = lambda x: iter(x._get_current_object())
    __contains__ = lambda x, i: i in x._get_current_object()
    __getslice__ = lambda x, i, j: x._get_current_object()[i:j]
    __add__ = lambda x, o: x._get_current_object() + o
    __sub__ = lambda x, o: x._get_current_object() - o
    __mul__ = lambda x, o: x._get_current_object() * o
    __floordiv__ = lambda x, o: x._get_current_object() // o
    __mod__ = lambda x, o: x._get_current_object() % o
    __divmod__ = lambda x, o: x._get_current_object().__divmod__(o)
    __pow__ = lambda x, o: x._get_current_object() ** o
    __lshift__ = lambda x, o: x._get_current_object() << o
    __rshift__ = lambda x, o: x._get_current_object() >> o
    __and__ = lambda x, o: x._get_current_object() & o
    __xor__ = lambda x, o: x._get_current_object() ^ o
    __or__ = lambda x, o: x._get_current_object() | o
    __div__ = lambda x, o: x._get_current_object().__div__(o)
    __truediv__ = lambda x, o: x._get_current_object().__truediv__(o)
    __neg__ = lambda x: -(x._get_current_object())
    __pos__ = lambda x: +(x._get_current_object())
    __abs__ = lambda x: abs(x._get_current_object())
    __invert__ = lambda x: ~(x._get_current_object())
    __complex__ = lambda x: complex(x._get_current_object())
    __int__ = lambda x: int(x._get_current_object())
    __long__ = lambda x: long(x._get_current_object())
    __float__ = lambda x: float(x._get_current_object())
    __oct__ = lambda x: oct(x._get_current_object())
    __hex__ = lambda x: hex(x._get_current_object())
    __index__ = lambda x: x._get_current_object().__index__()
    __coerce__ = lambda x, o: x.__coerce__(x, o)
    __enter__ = lambda x: x.__enter__()
    __exit__ = lambda x, *a, **kw: x.__exit__(*a, **kw)
