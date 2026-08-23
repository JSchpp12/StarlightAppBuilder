"""On-disk layout constants for the compressed-texture container formats that
basisu emits.

These mirror the packed structs in the bundled BasisUniversal headers
(transcoder/basisu_transcoder.h and transcoder/basisu_file_headers.h) so the
completeness verifier in TextureEncoder can parse a file's header without
pulling in any image-library dependency. All multi-byte fields are
little-endian: BasisUniversal's packed_uint<N> stores the low byte first
(m_bytes[i] = (v >> (i * 8)) & 0xFF).

The default basisu output used by prep-media is .ktx2; the legacy .basis
container constants are included for completeness / when use_basis_file_type
is set.
"""

# ---------------------------------------------------------------------------
# KTX2 container (Khronos KTX2 spec)
# ---------------------------------------------------------------------------

# File identifier / magic. Source: g_ktx2_file_identifier in
# BasisUniversal/transcoder/basisu_transcoder.cpp.
KTX2_IDENTIFIER = bytes([
    0xAB, 0x4B, 0x54, 0x58, 0x20, 0x32, 0x30, 0xBB,
    0x0D, 0x0A, 0x1A, 0x0A,
])

# Fixed header size: identifier(12) + 9*u32(36) + 4*u32(16) + 2*u64(16) = 80.
# Layout (offset: field):
#   0  identifier[12]
#   12 vkFormat          (u32)        44 supercompressionScheme (u32)
#   16 typeSize          (u32)        48 dfdByteOffset         (u32)
#   20 pixelWidth        (u32)        52 dfdByteLength         (u32)
#   24 pixelHeight       (u32)        56 kvdByteOffset         (u32)
#   28 pixelDepth        (u32)        60 kvdByteLength         (u32)
#   32 layerCount        (u32)        64 sgdByteOffset         (u64)
#   36 faceCount         (u32)        72 sgdByteLength         (u64)
#   40 levelCount        (u32)
# The level index array (ktx2_level_index entries) begins immediately after,
# at offset 80.
KTX2_HEADER_SIZE = 80

# Level index entry: byteOffset(u64) + byteLength(u64) + uncompressedByteLength(u64).
KTX2_LEVEL_INDEX_ENTRY_SIZE = 24

# Offset of the levelCount field (m_level_count) within the header. It is the
# 8th u32 field: 12 + 7 * 4 = 40.
KTX2_LEVEL_COUNT_OFFSET = 40

# Optional data-block byte-offset/length fields in the header, expressed as
# (field_offset, size_in_bytes_of_each_of_offset_and_length):
#   dfd: m_dfd_byte_offset(u32) @48, m_dfd_byte_length(u32) @52
#   kvd: m_kvd_byte_offset(u32) @56, m_kvd_byte_length(u32) @60
#   sgd: m_sgd_byte_offset(u64) @64, m_sgd_byte_length(u64) @72
KTX2_BLOCK_FIELDS = (
    (48, 4),  # dfd
    (56, 4),  # kvd
    (64, 8),  # sgd
)

# ---------------------------------------------------------------------------
# Basis (.basis) container (BasisUniversal/transcoder/basisu_file_headers.h)
# ---------------------------------------------------------------------------

# m_sig == cBASISSigValue == ('B' << 8) | 's' == 0x4273, stored little-endian as
# 0x73, 0x42. Basis file header layout (offset: field):
#   0  m_sig            (u16)     12 m_data_crc16     (u16)
#   2  m_ver            (u16)     14 m_total_slices  (u24)
#   4  m_header_size    (u16)     ...
#   6  m_header_crc16   (u16)     8  m_data_size     (u32)
BASIS_SIG = bytes([0x73, 0x42])

# Minimum bytes needed to read m_header_size and m_data_size: m_data_size is a
# u32 at offset 8 (ends at 12); 16 is a safe lower bound that also covers
# m_data_crc16.
BASIS_MIN_HEADER_SIZE = 16

# m_header_size (packed_uint<2>) field offset: 3rd field after m_sig@0, m_ver@2.
BASIS_HEADER_SIZE_FIELD_OFFSET = 4

# m_data_size (packed_uint<4>) field offset: after m_sig@0, m_ver@2,
# m_header_size@4, m_header_crc16@6.
BASIS_DATA_SIZE_FIELD_OFFSET = 8