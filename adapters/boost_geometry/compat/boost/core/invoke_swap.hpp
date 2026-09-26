// Compatibility shim for building Boost.Geometry `develop` against the system Boost 1.83.
//
// Boost.Core 1.84 renamed boost::swap to boost::core::invoke_swap and added this header;
// Boost.Geometry develop includes it (karney_inverse.hpp and the rtree node allocators).
// Boost 1.83 only has <boost/core/swap.hpp>.  This shim provides invoke_swap on top of
// the 1.83 implementation, with the same semantics (ADL swap, falling back to std::swap,
// element-wise for arrays).  build.sh puts this directory on the include path *after*
// the develop headers, and only for the develop build.
#ifndef BOOST_CORE_INVOKE_SWAP_HPP
#define BOOST_CORE_INVOKE_SWAP_HPP

#include <boost/core/swap.hpp>

namespace boost {
namespace core {

template <class T>
BOOST_GPU_ENABLED inline void invoke_swap(T &left, T &right)
    noexcept(noexcept(::boost_swap_impl::swap_impl(left, right)))
{
    ::boost_swap_impl::swap_impl(left, right);
}

} // namespace core
} // namespace boost

#endif // BOOST_CORE_INVOKE_SWAP_HPP
