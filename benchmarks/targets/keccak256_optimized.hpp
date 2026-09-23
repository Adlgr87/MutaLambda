inline void keccak_f1600(uint64_t A[25]) {
    static const uint64_t RC[24] = {
        0x0000000000000001ULL, 0x0000000000008082ULL, 0x800000000000808AULL,
        0x8000000080008000ULL, 0x000000000000808BULL, 0x0000000080000001ULL,
        0x8000000080008081ULL, 0x8000000000008009ULL, 0x000000000000008AULL,
        0x0000000000000088ULL, 0x0000000080008009ULL, 0x000000008000000AULL,
        0x000000008000808BULL, 0x800000000000008BULL, 0x8000000000008089ULL,
        0x8000000000008003ULL, 0x8000000000008002ULL, 0x8000000000000080ULL,
        0x000000000000800AULL, 0x800000008000000AULL, 0x8000000080008081ULL,
        0x8000000000008080ULL, 0x0000000080000001ULL, 0x8000000080008008ULL
    };

    for (int round = 0; round < 24; round++) {
        // θ (theta)
        uint64_t C[5], D[5];
        for (int x = 0; x < 5; x++)
            C[x] = A[x] ^ A[x + 5] ^ A[x + 10] ^ A[x + 15] ^ A[x + 20];
        for (int x = 4; x >= 0; x--) {
            const uint64_t c1 = C[(x + 1) % 5];
            D[x] = C[(x + 4) % 5] ^ ((c1 << 1) | (c1 >> 63));
        }
        for (int x = 0; x < 5; x++)
            for (int y = 0; y < 5; y++)
                A[x + y * 5] ^= D[x];

        // ρ (rho) + π (pi) — rotation chain
        {
            int x = 1, y = 0;
            uint64_t current = A[x + y * 5];
            for (int t = 0; t < 24; t++) {
                const int nx = y;
                const int ny = (2 * x + 3 * y) % 5;
                const uint64_t temp = A[nx + ny * 5];
                const int shift = (int)(((t + 1) * (t + 2)) / 2) & 63;
                A[nx + ny * 5] = (shift == 0)
                    ? current
                    : (current << shift) | (current >> (64 - shift));
                current = temp;
                x = nx;
                y = ny;
            }
        }

        // χ (chi)
        for (int y = 0; y < 5; y++) {
            uint64_t tmp[5];
            for (int x = 0; x < 5; x++) tmp[x] = A[x + y * 5];
            for (int x = 0; x < 5; x++)
                A[x + y * 5] = tmp[x] ^ ((~tmp[(x + 1) % 5]) & tmp[(x + 2) % 5]);
        }

        // ι (iota)
        A[0] ^= RC[round];
    }
}