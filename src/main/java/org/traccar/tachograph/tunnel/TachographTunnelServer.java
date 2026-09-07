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

import io.netty.bootstrap.ServerBootstrap;
import io.netty.channel.Channel;
import io.netty.channel.ChannelInitializer;
import io.netty.channel.ChannelOption;
import io.netty.channel.group.ChannelGroup;
import io.netty.channel.group.DefaultChannelGroup;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioServerSocketChannel;
import io.netty.handler.timeout.IdleStateHandler;
import io.netty.util.concurrent.GlobalEventExecutor;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.traccar.EventLoopGroupFactory;
import org.traccar.LifecycleObject;
import org.traccar.config.Config;
import org.traccar.config.Keys;
import org.traccar.database.DeviceLookupService;

import jakarta.inject.Inject;
import jakarta.inject.Singleton;

import java.net.InetSocketAddress;

/**
 * Listens for the tachograph data connections that FMC650 units open when they are told to
 * start a remote download.
 *
 * <p>This is a second listener alongside the normal Teltonika tracking port: the device keeps
 * reporting positions on its usual connection and opens a separate socket here for the duration
 * of a download. Configure the device's remote-tachograph server to this host and to
 * {@code tacho.tunnel.port}.
 *
 * <p>The listener stays off unless the tachograph module is enabled and a port is configured, so
 * an installation that does not use tachographs opens no extra ports.
 */
@Singleton
public class TachographTunnelServer implements LifecycleObject {

    private static final Logger LOGGER = LoggerFactory.getLogger(TachographTunnelServer.class);

    private final Config config;
    private final EventLoopGroupFactory eventLoopGroupFactory;
    private final TachographTunnelRegistry registry;
    private final DeviceLookupService deviceLookupService;

    private final ChannelGroup channelGroup = new DefaultChannelGroup(GlobalEventExecutor.INSTANCE);

    @Inject
    public TachographTunnelServer(
            Config config,
            EventLoopGroupFactory eventLoopGroupFactory,
            TachographTunnelRegistry registry,
            DeviceLookupService deviceLookupService) {
        this.config = config;
        this.eventLoopGroupFactory = eventLoopGroupFactory;
        this.registry = registry;
        this.deviceLookupService = deviceLookupService;
    }

    @Override
    public void start() throws Exception {
        if (!config.getBoolean(Keys.TACHO_ENABLED)) {
            return;
        }
        int port = config.getInteger(Keys.TACHO_TUNNEL_PORT);
        if (port <= 0) {
            LOGGER.info("Tachograph tunnel disabled: set tacho.tunnel.port to enable remote downloads");
            return;
        }

        int idleSeconds = config.getInteger(Keys.TACHO_TUNNEL_IDLE_TIMEOUT);

        ServerBootstrap bootstrap = new ServerBootstrap()
                .group(eventLoopGroupFactory.getBossGroup(), eventLoopGroupFactory.getWorkerGroup())
                .channel(NioServerSocketChannel.class)
                .childOption(ChannelOption.TCP_NODELAY, true)
                .childOption(ChannelOption.SO_KEEPALIVE, true)
                .childHandler(new ChannelInitializer<SocketChannel>() {
                    @Override
                    protected void initChannel(SocketChannel channel) {
                        channel.pipeline().addLast(new IdleStateHandler(0, 0, idleSeconds));
                        channel.pipeline().addLast(
                                new TachographTunnelHandler(registry, deviceLookupService));
                    }
                });

        String address = config.getString(Keys.TACHO_TUNNEL_ADDRESS);
        if (address == null || address.isBlank()) {
            bind(bootstrap, new InetSocketAddress(port));
        } else {
            for (String value : address.split(",")) {
                bind(bootstrap, new InetSocketAddress(value.trim(), port));
            }
        }
        LOGGER.info("Tachograph tunnel listening on port {}", port);
    }

    private void bind(ServerBootstrap bootstrap, InetSocketAddress endpoint) {
        Channel channel = bootstrap.bind(endpoint).syncUninterruptibly().channel();
        if (channel != null) {
            channelGroup.add(channel);
        }
    }

    @Override
    public void stop() {
        channelGroup.close().awaitUninterruptibly();
    }
}
