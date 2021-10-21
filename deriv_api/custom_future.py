from __future__ import annotations
import asyncio
from asyncio import Future, CancelledError, InvalidStateError
from typing import Any, Optional, TypeVar, Union, Callable
import weakref

_T = TypeVar("_T")
_S = TypeVar("_S")


class CustomFuture(Future):
    """A class that extend asyncio Future class and has some more convenient methods
    Just like Promise in JS or Future in Perl"""
    def __init__(self, *, loop: Optional[asyncio.AbstractEventLoop] = None, label: Optional[str] = None) -> None:
        super().__init__(loop=loop)
        if not label:
            label = f"Future {id(self)}"
        self.label = label

    @classmethod
    def wrap(cls, future: Future) -> CustomFuture:
        """Wrap an Asyncio Future to a CustomFuture"""
        if isinstance(future, cls):
            return future

        custom_future = cls(loop=future.get_loop())
        custom_future.cascade(future)
        weak_future = weakref.ref(future)

        def cancel_cb(cb_future: Future):
            future = weak_future()
            if cb_future.cancelled() and not future.done():
                try:
                    cb_future.result()
                except CancelledError as err:
                    future.cancel(*(err.args))

        custom_future.add_done_callback(cancel_cb)
        return custom_future

    def resolve(self, *args: Any) -> CustomFuture:
        """Set result on the future"""
        super().set_result(*args)
        return self

    def reject(self, *args: Union[type, BaseException]) -> CustomFuture:
        """Set exception on the future"""
        super().set_exception(*args)
        return self

    def is_pending(self) -> bool:
        """Check if the future is pending (not done)"""
        return not self.done()

    def is_resolved(self) -> bool:
        """check if the future is resolved (result set)"""
        return self.done() and not self.cancelled() and not self.exception()

    def is_rejected(self) -> bool:
        """check if the future is rejected (excetion set)"""
        return self.done() and not self.cancelled() and self.exception()

    def is_cancelled(self) -> bool:
        """check if the future is cancelled"""
        return self.cancelled()

    def cascade(self, future: Future) -> CustomFuture:
        """copy another future result to itself"""
        if self.done():
            raise InvalidStateError('invalid state')

        def done_callback(f: Future) -> None:
            try:
                result = f.result()
                self.set_result(result)
            except CancelledError as err:
                self.cancel(*(err.args))
            except BaseException as err:
                self.set_exception(err)

        future.add_done_callback(done_callback)
        return self

    def then(self, then_callback: Union[Callable[[Any], Any], None], else_callback: Union[Callable[[Any], Any], None] = None) -> CustomFuture:
        """Simulate Perl Future's 'then' function.
        Parameters:
        then_callback: the cb function that will be called when the original Future is resolved
        else_callback: the cb function that will be called when the original Future is rejected,
            can be None

        Both cb function should return a Future. The Future returned by the function 'then'
        will have same result of cb returned Future.
        """
        new_future = CustomFuture(loop=self.get_loop())

        def done_callback(myself: CustomFuture) -> None:
            f: Optional[CustomFuture] = None
            if myself.is_cancelled():
                new_future.cancel('Upstream future cancelled')
                return

            if myself.is_rejected() and else_callback:
                f = else_callback(myself.exception())
            elif myself.is_resolved() and then_callback:
                f = then_callback(myself.result())

            if f is None:
                new_future.cascade(myself)
                return

            def inside_callback(internal_future: CustomFuture) -> None:
                new_future.cascade(internal_future)

            f.add_done_callback(inside_callback)

        self.add_done_callback(done_callback)
        return new_future

    def catch(self, else_callback: Callable[[_S], Any]) -> CustomFuture:
        """An variant of 'then' function. it can only get an 'else_cb' which will be run when the future rejected"""
        return self.then(None, else_callback)
