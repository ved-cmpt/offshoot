/*
 * nonet: run a command with networking disabled.
 *
 * Installs a seccomp filter, inherited by every descendant and impossible to
 * remove, that makes socket() fail for every address family except AF_UNIX and
 * disables io_uring (which can create sockets without calling socket()). Then it
 * closes inherited file descriptors above stderr and execs the command.
 *
 * Fails closed: if the filter cannot be installed, the command does not run.
 * See ADR-009 in docs/ARCHITECTURE_DECISIONS.md.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <seccomp.h>
#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>

static int install_filter(void) {
    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
    int rc;

    if (ctx == NULL) {
        return -ENOMEM;
    }
    rc = seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EACCES), SCMP_SYS(socket), 1,
                          SCMP_A0(SCMP_CMP_NE, AF_UNIX));
    if (rc == 0) {
        rc = seccomp_rule_add(ctx, SCMP_ACT_ERRNO(ENOSYS), SCMP_SYS(io_uring_setup), 0);
    }
    if (rc == 0) {
        rc = seccomp_load(ctx);
    }
    seccomp_release(ctx);
    return rc;
}

int main(int argc, char **argv) {
    int rc;

    if (argc < 2) {
        fprintf(stderr, "usage: nonet command [args...]\n");
        return 125;
    }
    rc = install_filter();
    if (rc != 0) {
        fprintf(stderr, "nonet: could not install seccomp filter: %d\n", rc);
        return 126;
    }
    close_range(3, ~0U, 0);
    execvp(argv[1], &argv[1]);
    perror("nonet: exec");
    return 127;
}
