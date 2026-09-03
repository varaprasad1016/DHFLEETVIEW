/*
 * Copyright 2026 DH FleetView contributors
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.traccar.tachograph.tunnel;

import io.netty.buffer.ByteBuf;
import io.netty.buffer.Unpooled;
import io.netty.channel.ChannelHandlerContext;
import io.netty.channel.SimpleChannelInboundHandler;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.database.DeviceLookupService;
import org.traccar.model.Device;

import java.nio.charset.StandardCharsets;

/**
 * Netty handler for one tachograph tunnel socket.
 *
 * <p>The device identifies itself first, using the same handshake Teltonika units perform on
 * their tracking connection: a two-byte big-endian length followed by the IMEI in ASCII. The
 * server answers with a single byte, {@code 0x01} to accept and {@code 0x00} to reject. Every
 * byte after that is opaque vehicle-unit traffic and is passed straight through in both
 * directions, so the server never has to understand the device's own framing.
 *
 * <p>A connection whose IMEI is unknown, or that sends payload before identifying itself, is
 * closed immediately — an unauthenticated socket must never be able to reach a download.
 */
public class TachographTunnelHandler extends SimpleChannelInboundHandler<ByteBuf> {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographTunnelHandler.class);

    private static final int MIN_IMEI_LENGTH = 8;
    private static final int MAX_IMEI_LENGTH = 32;

    private static final byte HANDSHAKE_ACCEPT = 0x01;
    private static final byte HANDSHAKE_REJECT = 0x00;

    private final TachographTunnelRegistry registry;
    private final DeviceLookupService deviceLookupService;

    private TunnelConnection connection;

    public TachographTunnelHandler(
            TachographTunnelRegistry registry, DeviceLookupService deviceLookupService) {
        this.registry = registry;
        this.deviceLookupService = deviceLookupService;
    }

    @Override
    protected void channelRead0(ChannelHandlerContext context, ByteBuf message) {
        if (connection == null) {
            handleHandshake(context, message);
        } else {
            byte[] data = new byte[message.readableBytes()];
            message.readBytes(data);
            connection.enqueue(data);
        }
    }

    private void handleHandshake(ChannelHandlerContext context, ByteBuf message) {
        if (message.readableBytes() < 2) {
            reject(context, "handshake shorter than the length prefix");
            return;
        }
        int length = message.readUnsignedShort();
        if (length < MIN_IMEI_LENGTH || length > MAX_IMEI_LENGTH || message.readableBytes() < length) {
            reject(context, "implausible identifier length " + length);
            return;
        }

        String uniqueId = message.readCharSequence(length, StandardCharsets.US_ASCII).toString().trim();
        if (!uniqueId.matches("[0-9A-Za-z._-]+")) {
            reject(context, "identifier contains unexpected characters");
            return;
        }

        Device device = deviceLookupService.lookup(new String[] {uniqueId});
        if (device == null) {
            LOGGER.warn("Rejecting tachograph tunnel from {}: unknown device {}",
                    context.channel().remoteAddress(), uniqueId);
            context.writeAndFlush(Unpooled.wrappedBuffer(new byte[] {HANDSHAKE_REJECT}))
                    .addListener(future -> context.close());
            return;
        }

        connection = new TunnelConnection(context.channel(), uniqueId, device.getId());
        registry.register(connection);
        context.writeAndFlush(Unpooled.wrappedBuffer(new byte[] {HANDSHAKE_ACCEPT}));

        // A device may append vehicle-unit bytes to the same TCP segment as its handshake.
        if (message.readableBytes() > 0) {
            byte[] data = new byte[message.readableBytes()];
            message.readBytes(data);
            connection.enqueue(data);
        }
    }

    private void reject(ChannelHandlerContext context, String reason) {
        LOGGER.warn("Rejecting tachograph tunnel from {}: {}", context.channel().remoteAddress(), reason);
        context.close();
    }

    @Override
    public void channelInactive(ChannelHandlerContext context) throws Exception {
        if (connection != null) {
            connection.markClosed("device disconnected");
            registry.deregister(connection);
        }
        super.channelInactive(context);
    }

    @Override
    public void exceptionCaught(ChannelHandlerContext context, Throwable cause) {
        LOGGER.warn("Tachograph tunnel error from {}: {}",
                context.channel().remoteAddress(), cause.getMessage());
        if (connection != null) {
            connection.markClosed(cause.getMessage());
        }
        context.close();
    }
}
