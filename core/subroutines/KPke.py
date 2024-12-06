from numpy import random

from core.utils.bits import byte_encode, byte_decode, compress, decompress
from core.utils.ntt import NTT
import core.constants as const
from core.utils.shake import sha3_512, prf

import numpy as np
from Crypto.Random import get_random_bytes


class KPke:
    def __init__(self, d, ntt):
        """
        Initializes a KPke object with a random seed
        :param d: a 32 byte seed
        :param ntt: A NTT object used for operations
        """
        assert len(d) == 32, "Seed must be 32 bytes"
        self.d = d
        self.k = const.K
        self.ntt = ntt
        self.encryption_key = None
        self.decryption_key = None
        self.A = [[[0] * const.N for _ in range(self.k)] for _ in range(self.k)]
        self.s_cap = [[0] * const.N for _ in range(self.k)]
        self.e_cap = [[0] * const.N for _ in range(self.k)]
        self.e = [[0] * const.N for _ in range(self.k)]
        self.s = [[0] * const.N for _ in range(self.k)]
        self.check = None

    def keygen(self, d=None):
        if self.encryption_key is not None and self.decryption_key is not None:
            return self.encryption_key, self.decryption_key
        self.d = d or self.d
        ro, sigma = sha3_512(self.d + self.k.to_bytes())
        n = 0
        for i in range(self.k):
            for j in range(self.k):
                self.A[i][j] = self.ntt.get_sample_ntt(ro + j.to_bytes() + i.to_bytes())
        for i in range(self.k):
            self.s[i] = self.ntt.get_sample_polyCBD(prf(sigma, n.to_bytes()))
            n += 1
        for j in range(self.k):
            self.e[j] = self.ntt.get_sample_polyCBD(prf(sigma, n.to_bytes()))
            n += 1
        self.s_cap = [self.ntt.ntt(self.s[i]) for i in range(self.k)]
        self.e_cap = [self.ntt.ntt(self.e[i]) for i in range(self.k)]
        t_cap = self._add_vectors(self._multiply_array_vector_modified(self.A, self.s_cap), self.e_cap)
        self.encryption_key = b''.join([byte_encode(t_cap[i], 12) for i in range(self.k)]) + ro
        self.decryption_key = b''.join([byte_encode(self.s_cap[i], 12) for i in range(self.k)])
        return self.encryption_key, self.decryption_key

    def encrypt(self, message, randomness, dec_key = None):
        self.encryption_key = dec_key or self.encryption_key
        n = 0
        t_cap = [byte_decode(self.encryption_key[i * 384: (i + 1) * 384], const.D) for i in range(self.k)]
        ro = self.encryption_key[384 * self.k: 384 * self.k + 32]
        for i in range(self.k):
            for j in range(self.k):
                self.A[i][j] = self.ntt.get_sample_ntt(ro + j.to_bytes() + i.to_bytes())
        y = [[0] * const.N for _ in range(self.k)]
        e1 = [[0] * const.N for _ in range(self.k)]
        for i in range(self.k):
            y[i] = self.ntt.get_sample_polyCBD(prf(randomness, n.to_bytes(), const.ETA), const.ETA)
            n += 1
        for j in range(self.k):
            e1[j] = self.ntt.get_sample_polyCBD(prf(randomness, n.to_bytes(), const.ETA_2), const.ETA_2)
            n += 1
        e2 = self.ntt.get_sample_polyCBD(prf(randomness, n.to_bytes(), const.ETA_2), const.ETA_2)
        y_cap = [self.ntt.ntt(y[i]) for i in range(self.k)]
        u = self._multiply_array_transpose_vector(self.A, y_cap)
        u = [self.ntt.ntt_inverse(u[i]) for i in range(self.k)]
        u = [self._add_vectors(u[i], e1[i]) for i in range(self.k)]
        mu = decompress(byte_decode(message, 1), 1)
        v = self.ntt.ntt_inverse(self._multiply_vector_vector(t_cap, y_cap))
        v = self._add_vectors(self._add_vectors(v, e2), mu)
        first_half_cipher = [byte_encode(compress(u[i], const.DU), const.DU) for i in range(self.k)]
        second_half_cipher = byte_encode(compress(v, const.DV), const.DV)
        cipher = b''.join(first_half_cipher)
        cipher += second_half_cipher
        self.check = t_cap
        return cipher

    def decrypt(self, cipher, dec_key=None):
        self.decryption_key = dec_key or self.decryption_key
        first_half = cipher[0:32 * const.DU * self.k]
        second_half = cipher[32 * const.DU * self.k:]
        u = [decompress(byte_decode(first_half[32 * const.DU * i: 32 * const.DU * (i + 1)], const.DU), const.DU) for
             i in range(self.k)]
        v = decompress(byte_decode(second_half, const.DV), const.DV)
        s_cap = [byte_decode(self.decryption_key[i * 384: (i + 1) * 384], 12) for i in range(self.k)]
        u_cap = [self.ntt.ntt(u[i]) for i in range(self.k)]
        w = self.ntt.ntt_inverse(self._multiply_vector_vector(s_cap, u_cap))
        w = self._sub_vector(v, w)
        message = byte_encode(compress(w, 1), 1)
        return message

    def _multiply_vector_vector(self, vec1, vec2):
        result = [0] * const.N
        for i in range(self.k):
            result = self._add_vectors(self.ntt.multiply_ntt(vec1[i], vec2[i]), result)
        return result

    def _multiply_array_vector_modified(self, array, vector):
        result = [[0] * const.N for _ in range(self.k)]
        for i in range(self.k):
            for j in range(self.k):
                result[i] = self._add_vectors(self.ntt.multiply_ntt(array[i][j], vector[j]), result[i])
        return result

    def _multiply_array_transpose_vector(self, array, vector):
        result = [[0] * const.N for _ in range(self.k)]
        for i in range(self.k):
            for j in range(self.k):
                result[i] = self._add_vectors(self.ntt.multiply_ntt(array[j][i], vector[j]), result[i])
        return result

    def _add_vectors(self, vec1, vec2):
        """
        Adds two vectors
        :param vec1:
        :param vec2:
        :return:
        """
        return np.add(vec1, vec2) % const.Q

    def _sub_vector(self, vec1, vec2):
        return np.subtract(vec1, vec2) % const.Q


ntt = NTT()
kpke = KPke(get_random_bytes(32), ntt)
enc_key, dec_key = kpke.keygen()

# (f'Encryption key: {enc_key}')
# print(f'Decryption key: {dec_key}')
#  # (f'len(enc_key): {len(enc_key)}')
#  # (f'len(dec_key): {len(dec_key)}')
message = get_random_bytes(32)
cipher_text = kpke.encrypt(message, get_random_bytes(32))
# plain_text = kpke.decrypt(cipher_text)
# print(f'OG: {message}')
# print(f'decoded: {plain_text}')
# print(f'Equal ?= {(plain_text == message)}')
